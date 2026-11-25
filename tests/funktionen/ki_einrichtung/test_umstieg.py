"""Umstieg von einer alten Version (claude, gemini, lokal) auf das eine genut (US4, SC-006).

Die Erkennung ist gefälscht; config.toml, .env und Projekte liegen immer in tmp_path."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from genut.config import laden
from genut.funktionen.ki_einrichtung import erkennung
from genut.modelle import gemini
from genut.projekt import Projekt
from genut.schema import Dokument
from genut.server import app

WURZEL = Path(__file__).resolve().parents[3]
FIXTURE = WURZEL / "tests" / "fixtures" / "integral"
KIS = ("claude_code", "gemini", "ollama")
ENV = b"# mein Schluessel\r\nGEMINI_API_KEY=AIzaALT-test-1234567890\r\nANDERES=1\r\n"

# Stand der alten Versionsdateien versionen/<name>.toml vor ihrer Löschung
ALT = {
    "claude": """\
# gen_Ut – Version: Claude (Claude Code CLI, läuft über dein Claude-Abo)
# Diese Datei wird beim Einrichten nach config.toml kopiert. Änderungen danach in config.toml.

[server]
host = "127.0.0.1"   # nur lokal erreichbar
port = 8765

[modell]
standard = "claude_code"
auswahl = ["claude_code", "gemini"]   # KIs im Schalter oben rechts

[claude_code]
befehl = "claude"
modell = ""           # leer = Standard der Claude-CLI

[gemini]
modell = ""           # leer = neuestes Gemini-Flash-Modell (bei Überlastung automatisch ein älteres)
# Schlüssel NICHT hier, sondern in der Datei .env:  GEMINI_API_KEY=…

[ollama]
url = "http://localhost:11434"
modell = "gemma3:4b"  # ~4B-Vision-Modell, läuft auf einem Laptop mit 16 GB RAM ohne Grafikkarte

[pages]
aktiv = false

[funktionen]
lernplan = true   # ausschalten: lernplan = false
pruefung = true   # braucht die Claude-CLI
""",
    "gemini": """\
# gen_Ut – Version: Gemini (gratis, braucht einen API-Schlüssel von Google AI Studio)
# Diese Datei wird beim Einrichten nach config.toml kopiert. Änderungen danach in config.toml.

[server]
host = "127.0.0.1"   # nur lokal erreichbar
port = 8765

[modell]
standard = "gemini"
auswahl = ["gemini", "claude_code"]   # KIs im Schalter oben rechts

[claude_code]
befehl = "claude"
modell = ""           # leer = Standard der Claude-CLI

[gemini]
modell = ""           # leer = neuestes Gemini-Flash-Modell (bei Überlastung automatisch ein älteres)
# Schlüssel NICHT hier, sondern in der Datei .env:  GEMINI_API_KEY=…

[ollama]
url = "http://localhost:11434"
modell = "gemma3:4b"  # ~4B-Vision-Modell, läuft auf einem Laptop mit 16 GB RAM ohne Grafikkarte

[pages]
aktiv = false

[funktionen]
lernplan = true   # ausschalten: lernplan = false
""",
    "lokal": """\
# gen_Ut – Version: Lokal (Ollama, alles bleibt auf deinem Computer) – EXPERIMENTELL
# Diese Datei wird beim Einrichten nach config.toml kopiert. Änderungen danach in config.toml.

[server]
host = "127.0.0.1"   # nur lokal erreichbar
port = 8765

[modell]
standard = "ollama"
auswahl = ["ollama", "gemini"]   # KIs im Schalter oben rechts

[claude_code]
befehl = "claude"
modell = ""           # leer = Standard der Claude-CLI

[gemini]
modell = ""           # leer = neuestes Gemini-Flash-Modell (bei Überlastung automatisch ein älteres)
# Schlüssel NICHT hier, sondern in der Datei .env:  GEMINI_API_KEY=…

[ollama]
url = "http://localhost:11434"
modell = "gemma3:4b"  # ~4B-Vision-Modell, läuft auf einem Laptop mit 16 GB RAM ohne Grafikkarte

[pages]
aktiv = false

[funktionen]
lernplan = true   # ausschalten: lernplan = false
""",
}


@pytest.fixture(autouse=True)
def abgeschottet(tmp_path, monkeypatch):
    """Nie die echte .env oder config.toml, nie eine echte KI oder Netz."""
    monkeypatch.setenv("GENUT_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setattr(gemini, "WURZEL", tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    for name in KIS:
        monkeypatch.setitem(erkennung._PRUEFUNGEN, name,
                            lambda cfg, name=name: erkennung._zustand(name, "bereit"))
    monkeypatch.setattr(erkennung, "transport", httpx.MockTransport(lambda anfrage: httpx.Response(503)))
    laden.cache_clear()
    erkennung.leeren()
    yield
    laden.cache_clear()
    erkennung.leeren()


def _dateien(ordner: Path) -> dict[str, bytes]:
    return {str(p.relative_to(ordner)): p.read_bytes() for p in sorted(ordner.rglob("*")) if p.is_file()}


@pytest.mark.parametrize("version", ALT)
def test_umstieg(version, tmp_path, projekte):
    config, env_datei = tmp_path / "config.toml", tmp_path / ".env"
    alt = ALT[version].encode("utf-8")
    config.write_bytes(alt)
    env_datei.write_bytes(ENV)
    p = Projekt.anlegen("Test Integral")
    shutil.copy(FIXTURE / "fotos" / "001.jpg", p.fotos / "001.jpg")
    p.inhalt_speichern(Dokument.model_validate_json((FIXTURE / "inhalt.json").read_text(encoding="utf-8")))
    projekt_vorher = _dateien(projekte)

    # echter Aufruf wie im Setup; der Befehl braucht weder KI noch Netz
    lauf = subprocess.run([sys.executable, "-m", "genut", "ki", "auswahl-ergaenzen"], cwd=WURZEL,
                          env=os.environ.copy(), capture_output=True, timeout=60)
    assert lauf.returncode == 0, lauf.stderr.decode(errors="replace")

    vorher, nachher = tomllib.loads(alt.decode()), tomllib.loads(config.read_text(encoding="utf-8"))
    auswahl = nachher["modell"]["auswahl"]
    assert sorted(auswahl) == sorted(KIS)
    assert auswahl[:2] == vorher["modell"]["auswahl"]  # bisherige Reihenfolge bleibt
    assert nachher["modell"]["standard"] == vorher["modell"]["standard"]

    alte_zeilen, neue_zeilen = alt.splitlines(keepends=True), config.read_bytes().splitlines(keepends=True)
    assert len(alte_zeilen) == len(neue_zeilen)
    anders = [(a, n) for a, n in zip(alte_zeilen, neue_zeilen) if a != n]
    assert len(anders) == 1
    alte_zeile, neue_zeile = anders[0]
    assert alte_zeile.startswith(b"auswahl = ") and neue_zeile.startswith(b"auswahl = ")
    assert neue_zeile.endswith(alte_zeile[alte_zeile.index(b"   #"):])  # Kommentar dahinter bleibt

    assert (tmp_path / "config.toml.bak").read_bytes() == alt
    assert env_datei.read_bytes() == ENV

    laden.cache_clear()
    with TestClient(app) as client:  # mit Start und Ende der App
        antwort = client.get("/api/projekte")
        assert antwort.status_code == 200
        assert [(e["slug"], e["name"]) for e in antwort.json()] == [(p.slug, "Test Integral")]
        assert client.get(f"/api/projekte/{p.slug}").status_code == 200
        antwort = client.get("/api/ki/zustaende")
        assert antwort.status_code == 200
        assert sorted(z["name"] for z in antwort.json()["zustaende"]) == sorted(KIS)

    assert _dateien(projekte) == projekt_vorher
    assert env_datei.read_bytes() == ENV
    assert gemini.schluessel() == "AIzaALT-test-1234567890"
