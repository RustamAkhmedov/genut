from datetime import date

import pytest
from fastapi.testclient import TestClient

from genut.config import laden
from genut.funktionen.lernplan import logik
from genut.server import app

HEUTE = date(2026, 11, 16)


@pytest.fixture
def client(monkeypatch, projekt_mit_inhalt):
    monkeypatch.setattr(logik, "heute", lambda: HEUTE)
    laden.cache_clear()
    yield TestClient(app)
    laden.cache_clear()


def test_anlegen_auflisten_laden(client, projekt_mit_inhalt):
    r = client.post("/api/lernplaene", json={"name": "P", "projekte": [projekt_mit_inhalt.slug],
                                             "termin": "2026-12-09", "wochentage": [0, 2, 5]})
    assert r.status_code == 200, r.text
    plan = r.json()
    liste = client.get("/api/lernplaene").json()
    assert [z["id"] for z in liste["aktuell"]] == [plan["id"]] and liste["archiv"] == []
    assert client.get(f"/api/lernplaene/{plan['id']}").json()["id"] == plan["id"]
    assert client.get("/api/lernplaene/lp-00000000").status_code == 404
    assert client.get("/api/lernplaene/x").status_code == 404
    assert client.post("/api/lernplaene", json={"name": ""}).status_code == 400


def test_schalter_aus_themen_bleiben(client, projekt_mit_inhalt, monkeypatch, tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text("[funktionen]\nlernplan = false\n", encoding="utf-8")
    monkeypatch.setenv("GENUT_CONFIG", str(cfg))
    laden.cache_clear()
    assert client.get("/api/lernplaene").status_code == 404
    r = client.get(f"/api/projekte/{projekt_mit_inhalt.slug}/themen")
    assert r.status_code == 200 and r.json() and {"id", "titel", "kurz", "umfang"} <= set(r.json()[0])
    assert client.get("/api/projekte/gibt-es-nicht/themen").status_code == 404
