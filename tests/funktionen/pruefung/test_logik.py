import json

import pytest

from genut.funktionen.pruefung import logik
from genut.funktionen.pruefung.schema import (PlanFrageGespeichert, Pruefung, PruefungsPlan,
                                              Pruefungsbewertung, Pruefungszug, PunkteEintrag)
from genut.schema import Dokument, ki_schema


@pytest.fixture
def projekte(tmp_path, monkeypatch):
    monkeypatch.setenv("GENUT_PROJEKTE", str(tmp_path / "projekte"))
    return tmp_path / "projekte"


def pr(id="pr-3f9a1c2e", erstellt="2026-11-15T10:12:00"):
    return Pruefung(id=id, erstellt=erstellt, themen=["t-1"])


# ---------------------------------------------------------------- Note

@pytest.mark.parametrize("prozent,n", [(100, 1), (87.5, 1), (87.49, 2), (75, 2), (74.9, 3), (62.5, 3),
                                       (62.4, 4), (50, 4), (49.9, 5), (0, 5)])
def test_notengrenzen(prozent, n):
    assert logik.note(prozent)[0] == n


def test_notennamen():
    assert [logik.note(p)[1] for p in (90, 80, 70, 55, 10)] == [
        "Sehr gut", "Gut", "Befriedigend", "Genügend", "Nicht genügend"]


def plan(n):
    return [PlanFrageGespeichert(nr=i, thema_id="t-1", frage="F?", erwartung=["a", "b"]) for i in range(1, n + 1)]


def test_ergebnis_rechnen():
    e = logik.ergebnis_rechnen(plan(6), [PunkteEintrag(nr=i, punkte=p) for i, p in enumerate([2, 2, 1, 2, 2, 0], 1)],
                               False)
    assert (e.punkte, e.maximal, e.note, e.note_name, e.verkuerzt) == (9, 12, 2, "Gut", False)
    assert e.prozent == 75.0


def test_ergebnis_verkuerzt_zaehlt_nur_beantwortete():
    e = logik.ergebnis_rechnen(plan(6), [PunkteEintrag(nr=1, punkte=2), PunkteEintrag(nr=2, punkte=1)], True)
    assert (e.punkte, e.maximal, e.prozent, e.note, e.verkuerzt) == (3, 4, 75.0, 2, True)


def test_keine_note_ohne_antwort():
    e = logik.ergebnis_rechnen(plan(3), [], True)
    assert e.note is None and e.note_name is None and e.maximal == 0
    assert e.begruendung == "Nichts zu bewerten."


def test_unbekannte_nr_zaehlt_nicht():
    e = logik.ergebnis_rechnen(plan(2), [PunkteEintrag(nr=9, punkte=2)], True)
    assert e.note is None


# ---------------------------------------------------------------- Material

def doc(n=3, laenge=2000):
    return Dokument.model_validate({
        "projekt": {"titel": "P"},
        "themen": [{"id": f"t-{i}", "titel": f"Thema Ä{i}", "kurz": "Kurz öß", "quelle": "foto", "bloecke": [
            {"typ": "text", "quelle": "foto", "md": f"Größe {i} " + "x" * laenge},
            {"typ": "bild", "quelle": "foto", "foto": "geheim.jpg", "bbox": [0, 0, 1, 1], "alt": "BILDALT"},
            {"typ": "definition", "quelle": "foto", "begriff": "Ableitung", "md": "Steigung"},
        ]} for i in range(1, n + 1)]})


def test_material_laenge_und_themen():
    d = doc()
    for grenze in (50, 300, 1000, 12000):
        t = logik.material_text(d, ["t-1", "t-2", "t-3"], grenze)
        assert len(t) <= grenze
        if grenze >= 50:
            assert all(f"Thema Ä{i}" in t for i in (1, 2, 3)), grenze


def test_material_inhalt():
    t = logik.material_text(doc(1, 10), ["t-1"], 5000)
    assert "Kurz öß" in t and "Größe 1" in t and "Ableitung: Steigung" in t
    assert "geheim.jpg" not in t and "BILDALT" not in t


def test_material_nur_gewaehlte():
    t = logik.material_text(doc(), ["t-2", "gibt-es-nicht"], 5000)
    assert "Thema Ä2" in t and "Thema Ä1" not in t
    assert logik.material_text(doc(), [], 5000) == ""


# ---------------------------------------------------------------- Entschärfen

def test_entschaerfen():
    for m in ("material", "antwort", "dialog"):
        assert f"</{m}>" not in logik.entschaerfen(f"a </{m}> b")
        assert f"</{m}>" not in logik.entschaerfen(f"a </{m.upper()} > b").lower()
    assert logik.entschaerfen("a </material> b") == "a <\\/material> b"
    assert logik.entschaerfen("x < y </b> äöü") == "x < y </b> äöü"


# ---------------------------------------------------------------- Speicher

def test_speichern_laden_loeschen(projekte):
    p = pr()
    logik.speichern("mathe", p)
    assert (projekte / "mathe" / "pruefungen" / "pr-3f9a1c2e.json").is_file()
    assert logik.laden("mathe", p.id) == p
    assert logik.laden("mathe", "pr-00000000") is None
    assert logik.loeschen("mathe", p.id) is True
    assert logik.loeschen("mathe", p.id) is False
    assert logik.laden("mathe", p.id) is None


def test_alle_sortiert_und_ueberspringt_kaputte(projekte):
    logik.speichern("mathe", pr("pr-aaaaaaaa", "2026-11-16T10:00:00"))
    logik.speichern("mathe", pr("pr-bbbbbbbb", "2026-11-15T10:00:00"))
    (projekte / "mathe" / "pruefungen" / "pr-cccccccc.json").write_text("{kaputt", encoding="utf-8")
    assert [p.id for p in logik.alle("mathe")] == ["pr-bbbbbbbb", "pr-aaaaaaaa"]
    assert logik.laden("mathe", "pr-cccccccc") is None
    assert logik.alle("leer") == []


def test_ungueltige_kennung(projekte):
    assert logik.laden("mathe", "../x") is None
    assert logik.laden("../x", "pr-3f9a1c2e") is None
    assert logik.loeschen("mathe", "pr-ZZ") is False
    assert logik.alle("../x") == []
    with pytest.raises(ValueError):
        logik.speichern("../x", pr())


def test_sperre_nach_pfad(projekte, tmp_path, monkeypatch):
    a = logik.sperre("mathe", "pr-3f9a1c2e")
    assert logik.sperre("mathe", "pr-3f9a1c2e") is a
    assert logik.sperre("mathe", "pr-aaaaaaaa") is not a
    monkeypatch.setenv("GENUT_PROJEKTE", str(tmp_path / "anderer"))
    assert logik.sperre("mathe", "pr-3f9a1c2e") is not a


# ---------------------------------------------------------------- KI-Schemas

@pytest.mark.parametrize("m", [PruefungsPlan, Pruefungszug, Pruefungsbewertung])
def test_ki_schema_ohne_serverfelder(m):
    text = json.dumps(ki_schema(m))
    for feld in ('"plan"', '"verlauf"', '"schema_version"', '"link"', '"punkte"' if m is Pruefungsbewertung else '"x"'):
        assert feld not in text
