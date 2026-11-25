"""Routen des Moduls, Schreibschutz (research.md R10, SC-005) und `PUT /api/ki` mit Zuständen (T013)."""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from genut import funktionen
from genut.config import laden
from genut.funktionen.ki_einrichtung import erkennung
from genut.schutz import schreibschutz
from genut.server import app

from .fake_server import WURZEL, fake_zustaende

CONFIG = """# Kommentar bleibt
[modell]
standard = "claude_code"   # Wunsch
auswahl = ["claude_code", "gemini", "ollama"]
"""


@pytest.fixture
def config(tmp_path, monkeypatch):
    pfad = tmp_path / "config.toml"
    pfad.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setenv("GENUT_CONFIG", str(pfad))
    laden.cache_clear()
    erkennung.leeren()
    yield pfad
    laden.cache_clear()
    erkennung.leeren()


@pytest.fixture
def fake(config, monkeypatch):
    """Ersetzt die Prüfungen; `stand` ist änderbar, `aufrufe` zählt je KI."""
    stand = {"claude_code": "bereit", "gemini": "problem", "ollama": "nicht_eingerichtet"}
    aufrufe = []

    def pruefung(name):
        def lauf(cfg):
            aufrufe.append(name)
            return erkennung._zustand(name, stand[name], "" if stand[name] == "bereit" else "Grund")
        return lauf

    for name in stand:
        monkeypatch.setitem(erkennung._PRUEFUNGEN, name, pruefung(name))
    return stand, aufrufe


def test_antwortformat(fake):
    antwort = TestClient(app).get("/api/ki/zustaende")
    assert antwort.status_code == 200
    daten = antwort.json()
    assert set(daten) == {"zustaende", "keine_bereit"} and daten["keine_bereit"] is False
    assert [(z["name"], z["zustand"]) for z in daten["zustaende"]] == [
        ("claude_code", "bereit"), ("gemini", "problem"), ("ollama", "nicht_eingerichtet")]
    assert set(daten["zustaende"][0]) == {"name", "zustand", "ursache", "aktion", "geprueft", "auftrag"}


def test_keine_bereit(fake):
    fake[0]["claude_code"] = "problem"
    assert TestClient(app).get("/api/ki/zustaende").json()["keine_bereit"] is True


def test_neu_umgeht_den_speicher(fake):
    stand, aufrufe = fake
    c = TestClient(app)
    c.get("/api/ki/zustaende")
    stand["gemini"] = "bereit"
    alt = c.get("/api/ki/zustaende?neu=0").json()["zustaende"]
    assert alt[1]["zustand"] == "problem" and len(aufrufe) == 3
    neu = c.get("/api/ki/zustaende?neu=1").json()["zustaende"]
    assert neu[1]["zustand"] == "bereit" and len(aufrufe) == 6


def test_modul_aus_404(config):
    config.write_text(CONFIG + "\n[funktionen]\nki_einrichtung = false\n", encoding="utf-8")
    laden.cache_clear()
    assert TestClient(app).get("/api/ki/zustaende").status_code == 404


@pytest.mark.parametrize("ki, name", [("gemini", "Gemini"), ("ollama", "Lokal")])
def test_put_nicht_bereite_ki_abgelehnt(fake, config, ki, name):
    funktionen.ki_zustand_quelle(erkennung.bereit)
    vorher = config.read_bytes()
    antwort = TestClient(app).put("/api/ki", json={"standard": ki})
    assert antwort.status_code == 400
    assert antwort.json() == {"detail": f"{name} ist nicht eingerichtet"}
    assert config.read_bytes() == vorher


def test_put_bereite_ki(fake, config):
    fake[0]["gemini"] = "bereit"
    funktionen.ki_zustand_quelle(erkennung.bereit)
    antwort = TestClient(app).put("/api/ki", json={"standard": "gemini"})
    assert antwort.status_code == 200 and antwort.json()["standard"] == "gemini"


def test_put_ohne_quelle_wie_bisher(config):
    assert TestClient(app).put("/api/ki", json={"standard": "ollama"}).status_code == 200
    assert 'standard = "ollama"' in config.read_text(encoding="utf-8")


# ---------------------------------------------------------------- Schreibschutz

PROBE = FastAPI()


@PROBE.post("/schreiben", dependencies=[Depends(schreibschutz)])
def _schreiben():
    return {"ok": True}


def _senden(kopf, basis="http://127.0.0.1:8765"):
    return TestClient(PROBE, base_url=basis).post("/schreiben", headers=kopf).status_code


@pytest.mark.parametrize("kopf", [
    {"X-Genut": "1"},
    {"X-Genut": "1", "Origin": "http://127.0.0.1:8765"},
    {"X-Genut": "1", "Host": "localhost:8765", "Origin": "http://localhost:8765"},
])
def test_schutz_erlaubt_eigene_oberflaeche(kopf):
    assert _senden(kopf) == 200


@pytest.mark.parametrize("kopf", [
    {},
    {"X-Genut": "0"},
    {"Origin": "http://127.0.0.1:8765"},
    {"X-Genut": "1", "Host": "evil.example:8765"},
    {"X-Genut": "1", "Host": "127.0.0.1:9999"},
    {"X-Genut": "1", "Host": "127.0.0.1"},
    {"X-Genut": "1", "Origin": "http://evil.example"},
    {"X-Genut": "1", "Origin": "null"},
    {"X-Genut": "1", "Origin": "http://localhost:8765"},  # anderer Wert als Host
    {"X-Genut": "1", "Origin": "http://127.0.0.1:9999"},
])
def test_schutz_lehnt_ab(kopf):
    assert _senden(kopf) == 403


def test_schutz_fremder_host_in_der_adresse():
    assert _senden({"X-Genut": "1"}, "http://evil.example:8765") == 403


def test_alle_schreibenden_routen_geschuetzt():
    """Gilt auch für später ergänzte Routen des Moduls (SC-005)."""
    from genut.funktionen.ki_einrichtung.routen import router

    for r in router.routes:
        if r.methods - {"GET", "HEAD", "OPTIONS"}:
            assert any(d.call is schreibschutz for d in r.dependant.dependencies), r.path


# ---------------------------------------------------------------- Entwicklungsserver

def test_fake_zustaende():
    assert fake_zustaende("gemini:problem, claude_code:bereit") == {
        "claude_code": "bereit", "gemini": "problem", "ollama": "nicht_eingerichtet"}
    with pytest.raises(ValueError):
        fake_zustaende("gemini:kaputt")


def test_fake_server_startet(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if k != "GENUT_CONFIG"}
    env |= {"GENUT_PROJEKTE": str(tmp_path / "projekte"),
            "GENUT_FAKE_KI": "claude_code:bereit,gemini:problem,ollama:nicht_eingerichtet"}
    p = subprocess.Popen([sys.executable, "-m", "tests.funktionen.ki_einrichtung.fake_server", str(port)],
                         cwd=WURZEL, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ende = time.monotonic() + 30
        while True:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ki/zustaende?neu=1", timeout=5) as r:
                    daten = json.load(r)
                break
            except OSError:
                assert p.poll() is None and time.monotonic() < ende, "fake_server startet nicht"
                time.sleep(0.2)
        assert [z["zustand"] for z in daten["zustaende"]] == ["bereit", "problem", "nicht_eingerichtet"]
    finally:
        p.terminate()
        p.wait(10)
