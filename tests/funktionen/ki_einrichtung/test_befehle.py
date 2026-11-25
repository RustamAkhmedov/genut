"""Unterbefehle `python -m genut ki …` (contracts/cli.md). Erkennung, Rechner und Netz sind gefälscht;
config.toml und .env liegen immer in tmp_path."""
from __future__ import annotations

import importlib
import io
import json
import os
import stat
import tomllib
from datetime import datetime

import pytest

from genut.__main__ import main
from genut.config import laden
from genut.funktionen.ki_einrichtung import daten, env, erkennung, rechner
from genut.modelle import gemini

# Im Paket verdeckt die Funktion `befehle` das gleichnamige Untermodul.
befehle = importlib.import_module("genut.funktionen.ki_einrichtung.befehle")

SCHLUESSEL = "AIzaGEHEIM-test-1234567890"


@pytest.fixture(autouse=True)
def abgeschottet(tmp_path, monkeypatch):
    """Nie die echte .env oder config.toml."""
    config = tmp_path / "config.toml"
    config.write_text('# Kommentar\n[modell]\nstandard = "gemini"\n'
                      'auswahl = ["claude_code", "gemini", "ollama"]\n', encoding="utf-8")
    monkeypatch.setenv("GENUT_CONFIG", str(config))
    monkeypatch.setattr(gemini, "WURZEL", tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    def verboten(*a, **kw):
        raise AssertionError("echte Prüfung")

    for name in ("zustaende", "zustand", "claude_befehl", "gemini_schluessel_pruefen", "ollama_modelle"):
        monkeypatch.setattr(erkennung, name, verboten)
    laden.cache_clear()
    yield config
    laden.cache_clear()


def lauf(*argv) -> int:
    try:
        main(["ki", *argv])
    except SystemExit as e:
        if isinstance(e.code, str):
            return 1
        return e.code or 0
    return 0


def _z(name, zustand="bereit", ursache="", aktion=""):
    return daten.KiZustand(name=name, zustand=zustand, ursache=ursache, aktion=aktion,
                           geprueft=datetime(2026, 1, 2, 3, 4, 5))


def _erkennung(monkeypatch, zustaende: dict, befehl="/heim/.local/bin/claude"):
    aufrufe = []

    def alle(neu=False):
        aufrufe.append(("alle", neu))
        return list(zustaende.values())

    def einer(name, neu=False):
        aufrufe.append((name, neu))
        return zustaende[name]

    monkeypatch.setattr(erkennung, "zustaende", alle)
    monkeypatch.setattr(erkennung, "zustand", einer)
    monkeypatch.setattr(erkennung, "claude_befehl", lambda befehl_=None: befehl)
    return aufrufe


GEMISCHT = {
    "claude_code": _z("claude_code", "problem", "nicht angemeldet", "anmelden"),
    "gemini": _z("gemini"),
    "ollama": _z("ollama", "nicht_eingerichtet", "", "einrichten"),
}


# ---------------------------------------------------------------- zustand


def test_zustand_alle_json(monkeypatch, capsys):
    aufrufe = _erkennung(monkeypatch, GEMISCHT)
    assert lauf("zustand", "--json") == 0
    aus = json.loads(capsys.readouterr().out)
    assert set(aus) == {"zustaende", "keine_bereit"}
    assert aus["keine_bereit"] is False
    assert aus["zustaende"][0] == {"name": "claude_code", "zustand": "problem", "ursache": "nicht angemeldet",
                                   "aktion": "anmelden", "geprueft": "2026-01-02T03:04:05", "auftrag": None}
    assert all("befehl" not in z for z in aus["zustaende"])
    assert aufrufe == [("alle", True)]


def test_zustand_keine_bereit_exit_0(monkeypatch, capsys):
    _erkennung(monkeypatch, {"gemini": _z("gemini", "nicht_eingerichtet", "", "schluessel")})
    assert lauf("zustand", "--json") == 0
    assert json.loads(capsys.readouterr().out)["keine_bereit"] is True


def test_zustand_text(monkeypatch, capsys):
    _erkennung(monkeypatch, GEMISCHT)
    assert lauf("zustand") == 0
    assert capsys.readouterr().out.splitlines() == [
        "Claude: Problem (nicht angemeldet)", "Gemini: bereit", "Lokal: nicht eingerichtet"]


@pytest.mark.parametrize("name, code", [("gemini", 0), ("ollama", 1), ("claude_code", 1)])
def test_zustand_eine_ki_exit_code(monkeypatch, capsys, name, code):
    aufrufe = _erkennung(monkeypatch, GEMISCHT)
    assert lauf("zustand", "--json", name) == code
    assert json.loads(capsys.readouterr().out)["name"] == name
    assert aufrufe == [(name, True)]
    assert lauf("zustand", name) == code


@pytest.mark.parametrize("zustand, mit_befehl", [("bereit", True), ("problem", True), ("nicht_eingerichtet", False)])
def test_zustand_claude_nennt_befehl(monkeypatch, capsys, zustand, mit_befehl):
    _erkennung(monkeypatch, {"claude_code": _z("claude_code", zustand)})
    lauf("zustand", "claude_code", "--json")
    aus = json.loads(capsys.readouterr().out)
    assert aus.get("befehl") == ("/heim/.local/bin/claude" if mit_befehl else None)
    assert ("befehl" in aus) is mit_befehl


def test_zustand_andere_ki_ohne_befehl(monkeypatch, capsys):
    _erkennung(monkeypatch, GEMISCHT)
    lauf("zustand", "gemini", "--json")
    assert "befehl" not in json.loads(capsys.readouterr().out)


def test_zustand_unbekannte_ki(monkeypatch):
    assert lauf("zustand", "openai") == 2


def test_ki_ohne_unterbefehl():
    assert lauf() == 2


# ---------------------------------------------------------------- modelle


def _rechner(monkeypatch, tags, grafik_gb=12):
    monkeypatch.setattr(rechner, "profil", lambda: daten.Rechnerprofil(
        ram_gb=32, grafik="nvidia", grafik_name="Karte", grafik_gb=grafik_gb, system="linux", frei_gb=None))
    monkeypatch.setattr(erkennung, "ollama_modelle", lambda url=None: tags)


def test_modelle_ohne_ollama_json(monkeypatch, capsys):
    _rechner(monkeypatch, None)
    assert lauf("modelle", "--json") == 0
    aus = json.loads(capsys.readouterr().out)
    assert set(aus) == {"profil", "vorschlaege", "vorhanden", "keins_gut"}
    assert aus["profil"] == {"ram_gb": 32, "grafik": "nvidia", "grafik_gb": 12, "frei_gb": None}
    assert len(aus["vorschlaege"]) == 3
    assert set(aus["vorschlaege"][0]) == set(daten.Modellvorschlag.model_fields)
    assert [v["vorgewaehlt"] for v in aus["vorschlaege"]] == [False, True, False]
    assert not any(v["vorhanden"] for v in aus["vorschlaege"])
    assert aus["vorhanden"] == [] and aus["keins_gut"] is False


def test_modelle_markiert_geladene(monkeypatch, capsys):
    _rechner(monkeypatch, [{"name": "gemma3:4b", "size": 1}], grafik_gb=2)
    assert lauf("modelle", "--json") == 0
    aus = json.loads(capsys.readouterr().out)
    assert [v["vorhanden"] for v in aus["vorschlaege"]] == [True, False, False]
    assert aus["keins_gut"] is True


def test_modelle_text(monkeypatch, capsys):
    _rechner(monkeypatch, None)
    assert lauf("modelle") == 0
    aus = capsys.readouterr().out
    assert "gemma3:4b" in aus and "qwen3-vl:8b" in aus and "gemma3:12b" in aus and "Läuft gut" in aus


# ---------------------------------------------------------------- gemini-pruefen, .env


def _pruefung(monkeypatch, ergebnis):
    gesehen = []

    def pruefen(schluessel, basis=None):
        gesehen.append(schluessel)
        return ergebnis

    monkeypatch.setattr(erkennung, "gemini_schluessel_pruefen", pruefen)
    return gesehen


def _stdin(monkeypatch, text):
    monkeypatch.setattr("sys.stdin", io.StringIO(text))


def _rechte_ok(pfad):
    if os.name != "nt":
        assert stat.S_IMODE(pfad.stat().st_mode) == 0o600


def test_gemini_speichert(tmp_path, monkeypatch, capsys):
    gesehen = _pruefung(monkeypatch, "ok")
    _stdin(monkeypatch, f"﻿  {SCHLUESSEL} \r\n")
    assert lauf("gemini-pruefen") == 0
    env_datei = tmp_path / ".env"
    assert env_datei.read_bytes() == f"GEMINI_API_KEY={SCHLUESSEL}\n".encode()
    _rechte_ok(env_datei)
    assert gesehen == [SCHLUESSEL]
    assert gemini.schluessel() == SCHLUESSEL
    aus = capsys.readouterr()
    assert SCHLUESSEL not in aus.out + aus.err
    assert list(tmp_path.glob(".*env*")) == [env_datei]  # keine Temporärdatei übrig


def test_gemini_ersetzt_zeile_andere_bleiben(tmp_path, monkeypatch):
    env_datei = tmp_path / ".env"
    env_datei.write_bytes(b"# Kommentar\r\nANDERES=1\r\nexport GEMINI_API_KEY='alt'\r\nGEMINI_API_KEY=alt2\r\nX=2")
    env_datei.chmod(0o644)
    _pruefung(monkeypatch, "ok")
    _stdin(monkeypatch, SCHLUESSEL)
    assert lauf("gemini-pruefen") == 0
    assert env_datei.read_bytes() == f"# Kommentar\r\nANDERES=1\r\nGEMINI_API_KEY={SCHLUESSEL}\r\nX=2".encode()
    _rechte_ok(env_datei)


def test_gemini_haengt_an(tmp_path):
    (tmp_path / ".env").write_bytes(b"ANDERES=1")
    env.schluessel_speichern(SCHLUESSEL)
    assert (tmp_path / ".env").read_bytes() == f"ANDERES=1\nGEMINI_API_KEY={SCHLUESSEL}\n".encode()


def test_gemini_geht_vor_google_zeile(tmp_path):
    """`gemini.schluessel()` nimmt die erste passende Zeile; die neue muss gewinnen."""
    (tmp_path / ".env").write_bytes(b"GOOGLE_API_KEY=fremd\nGEMINI_API_KEY=alt\n")
    env.schluessel_speichern(SCHLUESSEL)
    assert (tmp_path / ".env").read_bytes() == f"GEMINI_API_KEY={SCHLUESSEL}\nGOOGLE_API_KEY=fremd\n".encode()
    assert gemini.schluessel() == SCHLUESSEL


@pytest.mark.parametrize("schluessel", ["", "a b", "a\nX=1", "a#b", "a'b", 'a"b', "ä", "x" * 201])
def test_speichern_lehnt_unbrauchbares_ab(tmp_path, schluessel):
    with pytest.raises(ValueError) as e:
        env.schluessel_speichern(schluessel)
    if len(schluessel) > 2:
        assert schluessel not in str(e.value)
    assert not (tmp_path / ".env").exists()


@pytest.mark.parametrize("ergebnis, code", [("abgelehnt", 1), ("keine_verbindung", 3)])
def test_gemini_fehler_speichert_nichts(tmp_path, monkeypatch, capsys, ergebnis, code):
    (tmp_path / ".env").write_bytes(b"GEMINI_API_KEY=alt\n")
    _pruefung(monkeypatch, ergebnis)
    _stdin(monkeypatch, SCHLUESSEL + "\n")
    assert lauf("gemini-pruefen") == code
    assert (tmp_path / ".env").read_bytes() == b"GEMINI_API_KEY=alt\n"
    aus = capsys.readouterr()
    assert SCHLUESSEL not in aus.out + aus.err


@pytest.mark.parametrize("eingabe", ["", "  \n", "x" * 201, "zwei woerter"])
def test_gemini_unbrauchbare_eingabe_ohne_anfrage(tmp_path, monkeypatch, eingabe):
    _stdin(monkeypatch, eingabe)  # die Prüfung bleibt „verboten“
    assert lauf("gemini-pruefen") == 1
    assert not (tmp_path / ".env").exists()


# ---------------------------------------------------------------- setzen, auswahl, standard


@pytest.mark.parametrize("name, wert", [
    ("modell.standard", "ollama"), ("ollama.modell", "qwen3-vl:8b"),
    ("ollama.url", "http://localhost:9999"), ("claude_code.befehl", "/heim/x/.local/bin/claude")])
def test_setzen(abgeschottet, name, wert):
    assert lauf("setzen", name, wert) == 0
    text = abgeschottet.read_text(encoding="utf-8")
    abschnitt, schluessel = name.split(".")
    assert tomllib.loads(text)[abschnitt][schluessel] == wert
    assert text.startswith("# Kommentar\n")


@pytest.mark.parametrize("name, wert", [
    ("server.host", "0.0.0.0"), ("gemini.modell", "x"), ("modell", "gemini"), ("modell.auswahl", "gemini"),
    ("modell.standard", "openai"), ("modell.standard", "")])
def test_setzen_unerlaubt(abgeschottet, capsys, name, wert):
    vorher = abgeschottet.read_bytes()
    assert lauf("setzen", name, wert) == 2
    assert abgeschottet.read_bytes() == vorher
    assert capsys.readouterr().err


def test_auswahl_ergaenzen(abgeschottet, capsys):
    abgeschottet.write_text('[modell]\nauswahl = ["gemini"]\n', encoding="utf-8")
    laden.cache_clear()
    assert lauf("auswahl-ergaenzen") == 0
    assert laden()["modell"]["auswahl"] == ["gemini", "claude_code", "ollama"]
    assert abgeschottet.with_name("config.toml.bak").exists()
    assert "claude_code, ollama" in capsys.readouterr().out
    assert lauf("auswahl-ergaenzen") == 0
    assert "vollständig" in capsys.readouterr().out


@pytest.mark.parametrize("bereit, erwartet", [
    (("ollama", "gemini", "claude_code"), "claude_code"), (("ollama", "gemini"), "gemini"),
    (("ollama",), "ollama"), ((), "")])
def test_standard_vorschlag(monkeypatch, capsys, bereit, erwartet):
    # Reihenfolge in `auswahl` spielt keine Rolle
    aufrufe = _erkennung(monkeypatch, {
        n: _z(n, "bereit" if n in bereit else "problem") for n in ("ollama", "gemini", "claude_code")})
    code = 0 if erwartet else 1
    assert lauf("standard-vorschlag", "--json") == code
    assert json.loads(capsys.readouterr().out) == {"standard": erwartet}
    assert lauf("standard-vorschlag") == code
    assert capsys.readouterr().out.strip() == erwartet
    assert aufrufe[0] == ("alle", True)
