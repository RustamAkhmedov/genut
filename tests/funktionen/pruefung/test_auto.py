"""`pruefung = "auto"` (specs/005b-ein-genut/research.md R3): die Prüfung gibt es nur, solange Claude bereit ist."""
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from genut import funktionen
from genut.config import laden
from genut.funktionen import pruefung
from genut.server import app

from .fake import FakeModell, einsetzen

T1 = "t-00000001"


def _config(monkeypatch, tmp_path, wert: str) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(f"[funktionen]\npruefung = {wert}\n", encoding="utf-8")
    monkeypatch.setenv("GENUT_CONFIG", str(cfg))
    laden.cache_clear()


@pytest.fixture(autouse=True)
def _auto(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path, '"auto"')
    yield
    laden.cache_clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def s(projekt_mit_inhalt):
    return projekt_mit_inhalt.slug


def quelle(monkeypatch, zustand: dict) -> list:
    """Fake-Erkennung; `zustand["claude_code"]` lässt sich im Test ändern. Gibt die Abfragen zurück."""
    abfragen = []

    def fn(name):
        abfragen.append(name)
        return zustand.get(name)

    monkeypatch.setattr(funktionen, "_ki_quelle", fn)
    return abfragen


def verfuegbar(c) -> bool:
    r = c.get("/api/pruefung/verfuegbar")
    assert r.status_code == 200, r.text
    return r.json()["verfuegbar"]


def alle_routen(c, s, pid="pr-00000000"):
    b = f"/api/projekte/{s}/pruefungen"
    for methode, pfad, kw in [("get", b, {}), ("post", b, {"json": {"themen": [T1], "fragen": 3}}),
                              ("get", f"{b}/{pid}", {}), ("post", f"{b}/{pid}/antwort", {"json": {"text": "x"}}),
                              ("post", f"{b}/{pid}/weiter", {}), ("post", f"{b}/{pid}/beenden", {}),
                              ("delete", f"{b}/{pid}", {})]:
        yield methode, pfad, getattr(c, methode)(pfad, **kw)


@pytest.mark.parametrize("wert,an", [(True, True), ("auto", True), (False, False), ("ja", False), (1, False)])
def test_aktiv_ohne_ki_abfrage(monkeypatch, wert, an):
    abfragen = quelle(monkeypatch, {"claude_code": False})
    assert pruefung.aktiv({"funktionen": {"pruefung": wert}}) is an
    assert abfragen == []


def test_wechsel_ohne_neustart(client, s, monkeypatch):
    einsetzen(monkeypatch, FakeModell())
    zustand = {"claude_code": True, "gemini": False}
    quelle(monkeypatch, zustand)
    assert verfuegbar(client) is True
    r = client.post(f"/api/projekte/{s}/pruefungen", json={"themen": [T1], "fragen": 3})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]

    zustand["claude_code"] = False
    assert verfuegbar(client) is False
    for methode, pfad, antwort in alle_routen(client, s, pid):
        assert antwort.status_code == 404, (methode, pfad)

    zustand["claude_code"] = True
    assert verfuegbar(client) is True
    assert client.get(f"/api/projekte/{s}/pruefungen/{pid}").status_code == 200  # nichts ging verloren


@pytest.mark.parametrize("fn", [None, lambda name: None, lambda name: 1 / 0])
def test_ohne_quelle_oder_unbekannt(client, s, monkeypatch, fn):
    monkeypatch.setattr(funktionen, "_ki_quelle", fn)
    assert verfuegbar(client) is False
    for methode, pfad, antwort in alle_routen(client, s):
        assert antwort.status_code == 404, (methode, pfad)


def test_ohne_modul_ki_einrichtung(monkeypatch, tmp_path, s):
    """Gelöschter Ordner genut/funktionen/ki_einrichtung/: niemand registriert eine Quelle, die Prüfung ist aus."""
    ohne = tmp_path / "ohne"
    ohne.mkdir()
    for n in funktionen.vorhanden():
        if n != "ki_einrichtung":
            (ohne / n).symlink_to(Path(funktionen.__path__[0]) / n, target_is_directory=True)
    monkeypatch.setattr(funktionen, "__path__", [str(ohne)])
    neu = FastAPI()
    assert "ki_einrichtung" not in funktionen.einhaengen_alle(neu)
    c = TestClient(neu)
    assert verfuegbar(c) is False
    for methode, pfad, antwort in alle_routen(c, s):
        assert antwort.status_code == 404, (methode, pfad)


def test_ki_status_fragt_pruefung_nicht_ab(client, monkeypatch):
    """`GET /api/ki` läuft bei jedem Seitenwechsel: `aktiv()` darf keine Erkennung auslösen."""
    def verboten(name):
        raise AssertionError("keine Erkennung beim Abruf von `module`")

    gerufen = []
    monkeypatch.setattr(funktionen, "_ki_quelle", lambda name: gerufen.append(name) or verboten(name))
    ki = client.get("/api/ki").json()
    assert "pruefung" in ki["module"] and gerufen == []


def test_true_immer_verfuegbar(client, s, monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path, "true")
    abfragen = quelle(monkeypatch, {"claude_code": False})
    assert verfuegbar(client) is True
    assert client.get(f"/api/projekte/{s}/pruefungen").status_code == 200
    assert abfragen == []


def test_false_ueberall_404(client, s, monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path, "false")
    quelle(monkeypatch, {"claude_code": True})
    assert client.get("/api/pruefung/verfuegbar").status_code == 404  # Modul aus wie in 005
    for methode, pfad, antwort in alle_routen(client, s):
        assert antwort.status_code == 404, (methode, pfad)
    assert "pruefung" not in client.get("/api/ki").json()["module"]
