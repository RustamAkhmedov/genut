from datetime import date

import pytest

from genut.funktionen.lernplan import logik
from genut.funktionen.lernplan.schema import Lernplan

HEUTE = date(2026, 11, 16)  # Montag


@pytest.fixture(autouse=True)
def _heute(monkeypatch):
    monkeypatch.setattr(logik, "heute", lambda: HEUTE)


def daten(slug, **kw):
    return {"name": "Plan", "projekte": [slug], "termin": "2026-12-09", "wochentage": [0, 2, 5], **kw}


def test_anlegen_und_laden(projekt_mit_inhalt):
    p = logik.anlegen(daten(projekt_mit_inhalt.slug))
    assert p.id.startswith("lp-") and p.zuordnung and p.start == HEUTE and not p.erledigt
    assert all(z.datum.weekday() in (0, 2, 5) and HEUTE <= z.datum < p.termin for z in p.zuordnung)
    assert logik.laden(p.id) == p
    assert [x.id for x in logik.alle()] == [p.id]
    assert logik.anlegen(daten(projekt_mit_inhalt.slug, name="B")).id != p.id
    assert len(logik.alle()) == 2


def test_loeschen(projekt_mit_inhalt):
    p = logik.anlegen(daten(projekt_mit_inhalt.slug))
    assert logik.loeschen(p.id) is True
    assert logik.loeschen(p.id) is False
    assert logik.laden(p.id) is None and logik.alle() == []


def test_ungueltige_kennung(projekte):
    for k in ("../x", "lp-ABCDEF12", "lp-1234567", "", "lp-12345678/../../x"):
        assert logik.laden(k) is None
        assert logik.loeschen(k) is False
    assert logik.alle() == []


def test_kaputte_datei_uebersprungen(projekt_mit_inhalt):
    p = logik.anlegen(daten(projekt_mit_inhalt.slug))
    (projekt_mit_inhalt.ordner.parent / ".lernplaene" / "lp-00000000.json").write_text("{kaputt", encoding="utf-8")
    assert [x.id for x in logik.alle()] == [p.id]
    assert logik.laden("lp-00000000") is None


def test_speichern_ueberschreibt(projekt_mit_inhalt):
    p = logik.anlegen(daten(projekt_mit_inhalt.slug))
    logik.speichern(p.model_copy(update={"name": "Neu"}))
    assert logik.laden(p.id).name == "Neu"


@pytest.mark.parametrize("aender, meldung", [
    ({"name": "  "}, "Name"),
    ({"name": "x" * 61}, "Name"),
    ({"termin": "2026-11-16"}, "Zukunft"),
    ({"termin": "2026-11-01"}, "Zukunft"),
    ({"termin": "kaputt"}, "Datum"),
    ({"wochentage": []}, "Wochentag"),
    ({"wochentage": [7]}, "Wochentage"),
    ({"projekte": []}, "Projekt"),
    ({"projekte": ["gibt-es-nicht"]}, "Inhalt"),
    ({"projekte": ["../x"]}, "Inhalt"),
    ({"termin": "2026-11-20", "wochentage": [5]}, "Lerntag"),  # Fr 20.11., nur Samstag
    ({"start": "2026-12-09"}, "Startdatum"),
])
def test_anlegen_fehler(projekt_mit_inhalt, aender, meldung):
    with pytest.raises(ValueError, match=meldung):
        logik.anlegen({**daten(projekt_mit_inhalt.slug), **aender})
    assert logik.alle() == []


def test_projekt_ohne_inhalt(projekte):
    from genut.projekt import Projekt

    p = Projekt.anlegen("Leer")
    with pytest.raises(ValueError, match="Inhalt"):
        logik.anlegen(daten(p.slug))


def test_alle_themen_ausgenommen(projekt_mit_inhalt):
    ids = [t["id"] for t in logik.lasten_der_projekte([projekt_mit_inhalt.slug]) and
           logik.projektdaten("x", projekt_mit_inhalt.inhalt())["themen"]]
    aus = [{"projekt": projekt_mit_inhalt.slug, "thema_id": i} for i in ids]
    with pytest.raises(ValueError, match="ausgenommen"):
        logik.anlegen(daten(projekt_mit_inhalt.slug, ausgenommen=aus))
    p = logik.anlegen(daten(projekt_mit_inhalt.slug, ausgenommen=aus[:1])) if len(aus) > 1 else None
    if p:
        assert {(z.projekt, z.thema_id) for z in p.zuordnung}.isdisjoint({(aus[0]["projekt"], aus[0]["thema_id"])})


def test_lasten_der_projekte(projekt_mit_inhalt):
    s = projekt_mit_inhalt.slug
    lasten = logik.lasten_der_projekte([s, "fehlt"])
    assert lasten and all(k[0] == s and v for k, v in lasten.items())
    erstes = next(iter(lasten))
    assert erstes not in logik.lasten_der_projekte([s], [erstes])
    assert logik.lasten_der_projekte(["fehlt"]) == {}


def test_plan_ist_lernplan_und_deterministisch(projekt_mit_inhalt):
    a = logik.anlegen(daten(projekt_mit_inhalt.slug))
    b = logik.anlegen(daten(projekt_mit_inhalt.slug))
    assert isinstance(a, Lernplan) and a.zuordnung == b.zuordnung
