"""logik.aendern und die Routen PATCH/DELETE (T015)."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from genut.funktionen.lernplan import logik
from genut.server import app

HEUTE = date(2026, 11, 16)  # Montag


@pytest.fixture(autouse=True)
def _heute(monkeypatch):
    monkeypatch.setattr(logik, "heute", lambda: HEUTE)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def plan(client, projekt_mit_inhalt):
    r = client.post("/api/lernplaene", json={"name": "Plan", "projekte": [projekt_mit_inhalt.slug],
                                             "termin": "2026-12-09", "wochentage": [0, 2, 5]})
    assert r.status_code == 200, r.text
    return r.json()


def _datei(plan):
    return logik._pfad(plan["id"]).read_bytes()


def test_name_aendern_ohne_neu_verteilen(plan, monkeypatch):
    def nie(*a, **k):
        raise AssertionError("neu_verteilen darf nicht laufen")
    monkeypatch.setattr(logik, "neu_verteilen", nie)
    neu = logik.aendern(plan["id"], {"name": "  Neu  "})
    assert neu.name == "Neu"
    assert logik.laden(plan["id"]).name == "Neu"


def test_name_aendern_bei_vergangenem_termin(plan, monkeypatch):
    monkeypatch.setattr(logik, "heute", lambda: date(2027, 1, 1))
    assert logik.aendern(plan["id"], {"name": "Archiv"}).name == "Archiv"


def test_termin_und_wochentage_verteilen_neu_erledigtes_bleibt(client, plan):
    z = logik.laden(plan["id"]).zuordnung[0]
    ziel = {"projekt": z.projekt, "thema_id": z.thema_id, "von": z.von, "bis": z.bis}
    assert client.put(f"/api/lernplaene/{plan['id']}/erledigt", json={**ziel, "erledigt": True}).status_code == 200
    r = client.patch(f"/api/lernplaene/{plan['id']}", json={"termin": "2026-12-23", "wochentage": [1, 3]})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["termin"] == "2026-12-23" and p["wochentage"] == [1, 3]
    gespeichert = logik.laden(plan["id"])
    assert any((e.projekt, e.thema_id, e.von, e.bis) == tuple(ziel.values()) for e in gespeichert.erledigt)
    erledigt_datum = {(s["thema_id"], s["von"], s["bis"]): s["datum"]
                      for t in p["tage"] for s in t["themen"] if s["status"] == "erledigt"}
    assert (z.thema_id, z.von, z.bis) in erledigt_datum
    for t in p["tage"]:
        for s in t["themen"]:
            if s["status"] != "erledigt":
                assert date.fromisoformat(s["datum"]).weekday() in (1, 3)


def test_thema_ausnehmen_und_projekt_entfernen(client, plan, projekt_mit_inhalt):
    themen = client.get(f"/api/projekte/{projekt_mit_inhalt.slug}/themen").json()
    assert len(themen) >= 2
    weg = {"projekt": projekt_mit_inhalt.slug, "thema_id": themen[0]["id"]}
    p = client.patch(f"/api/lernplaene/{plan['id']}", json={"ausgenommen": [weg]}).json()
    ids = {s["thema_id"] for t in p["tage"] for s in t["themen"]}
    assert themen[0]["id"] not in ids and p["ausgenommen"] == [weg]
    assert p["unverteilt"] == []


def test_ausgenommen_entfernter_projekte_faellt_weg(plan, projekt_mit_inhalt):
    from genut.projekt import Projekt
    zweit = Projekt.anlegen("Zweit")
    zweit.inhalt_speichern(projekt_mit_inhalt.inhalt())
    neu = logik.aendern(plan["id"], {"projekte": [zweit.slug], "ausgenommen": [
        {"projekt": projekt_mit_inhalt.slug, "thema_id": "t-x"}]})
    assert neu.projekte == [zweit.slug] and neu.ausgenommen == []
    assert {z.projekt for z in neu.zuordnung} == {zweit.slug}


@pytest.mark.parametrize("daten, meldung", [
    ({"name": " "}, "Name"),
    ({"name": "x" * 61}, "60"),
    ({"termin": "2026-11-16"}, "Zukunft"),
    ({"termin": "kaputt"}, "Datum"),
    ({"start": "2026-12-09"}, "Startdatum"),
    ({"start": "2026-12-20"}, "Startdatum"),
    ({"wochentage": []}, "Wochentag"),
    ({"wochentage": [7]}, "Wochentage"),
    ({"wochentage": [1, 1]}, "Wochentage"),
    ({"projekte": []}, "Projekt"),
    ({"projekte": ["gibt-es-nicht"]}, "Inhalt"),
    ({"ausgenommen": "x"}, "ausgenommen"),
    ({"termin": "2026-11-20", "wochentage": [5]}, "Lerntag"),
])
def test_fehler_400_datei_unveraendert(client, plan, daten, meldung):
    vorher = _datei(plan)
    r = client.patch(f"/api/lernplaene/{plan['id']}", json=daten)
    assert r.status_code == 400 and meldung in r.json()["detail"], r.text
    assert _datei(plan) == vorher


def test_alle_themen_ausgenommen(client, plan, projekt_mit_inhalt):
    themen = client.get(f"/api/projekte/{projekt_mit_inhalt.slug}/themen").json()
    alle = [{"projekt": projekt_mit_inhalt.slug, "thema_id": t["id"]} for t in themen]
    vorher = _datei(plan)
    r = client.patch(f"/api/lernplaene/{plan['id']}", json={"ausgenommen": alle})
    assert r.status_code == 400 and "ausgenommen" in r.json()["detail"]
    assert _datei(plan) == vorher


def test_unbekannt_404(client):
    assert client.patch("/api/lernplaene/lp-00000000", json={"name": "x"}).status_code == 404
    assert client.patch("/api/lernplaene/ungueltig", json={"name": "x"}).status_code == 404
    assert client.delete("/api/lernplaene/lp-00000000").status_code == 404
    assert client.delete("/api/lernplaene/ungueltig").status_code == 404


def test_loeschen_laesst_projekte_unberuehrt(client, plan, projekt_mit_inhalt):
    inhalt = (projekt_mit_inhalt.dir / "inhalt.json").read_bytes() if hasattr(projekt_mit_inhalt, "dir") else None
    r = client.delete(f"/api/lernplaene/{plan['id']}")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert client.get(f"/api/lernplaene/{plan['id']}").status_code == 404
    assert client.delete(f"/api/lernplaene/{plan['id']}").status_code == 404
    assert client.get(f"/api/projekte/{projekt_mit_inhalt.slug}/themen").json()
    if inhalt is not None:
        assert (projekt_mit_inhalt.dir / "inhalt.json").read_bytes() == inhalt


def test_gekuerztes_bis_bleibt_abhakbar(client, plan, projekt_mit_inhalt):
    """Ist ein Thema nach dem Plananlegen kürzer geworden, zeigt die Antwort ein gekürztes `bis`, dazu
    `bis_gespeichert`. Mit diesem Wert lässt sich das Stück abhaken; der Status wird `erledigt`."""
    p = logik.laden(plan["id"])
    z = p.zuordnung[-1]
    kurz = z.model_copy(update={"bis": z.bis + 5})  # simuliert: gespeichertes bis > aktuelle Einheiten
    zu = [kurz if x is z else x for x in p.zuordnung]
    logik.speichern(p.model_copy(update={"zuordnung": zu}))
    a = client.get(f"/api/lernplaene/{plan['id']}").json()
    s = [s for t in a["tage"] for s in t["themen"] if s["thema_id"] == z.thema_id and s["von"] == z.von][-1]
    assert s["bis"] == z.bis != kurz.bis
    assert s["bis_gespeichert"] == kurz.bis
    r = client.put(f"/api/lernplaene/{plan['id']}/erledigt",
                   json={"projekt": s["projekt"], "thema_id": s["thema_id"], "von": s["von"],
                         "bis": s["bis_gespeichert"], "erledigt": True})
    assert r.status_code == 200
    assert [(e.von, e.bis) for e in logik.laden(plan["id"]).erledigt if e.thema_id == z.thema_id
            and e.von == z.von] == [(z.von, kurz.bis)]
    s2 = [s for t in r.json()["tage"] for s in t["themen"] if s["thema_id"] == z.thema_id and s["von"] == z.von][-1]
    assert s2["status"] == "erledigt"
