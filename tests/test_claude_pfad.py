"""Der Claude-Adapter findet die CLI auch am Ort des offiziellen Installers (~/.local/bin), wenn sie nicht
im Suchpfad liegt, so wie es die Erkennung anzeigt (Feature 005b)."""
from pathlib import Path

import pytest

from genut.modelle import claude_code


@pytest.fixture
def heim(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(claude_code.shutil, "which", lambda name: None)
    ziel = tmp_path / ".local" / "bin" / ("claude.exe" if claude_code.os.name == "nt" else "claude")
    ziel.parent.mkdir(parents=True)
    return ziel


def test_standardbefehl_nutzt_installer_ort(heim):
    heim.write_text("", encoding="utf-8")
    assert claude_code.ClaudeCode({"befehl": "claude"}).befehl == str(heim)


def test_ohne_installation_bleibt_der_befehl(heim):
    assert claude_code.ClaudeCode({"befehl": "claude"}).befehl == "claude"


def test_vorhandener_eigener_befehl_wird_nicht_ersetzt(heim, monkeypatch):
    heim.write_text("", encoding="utf-8")
    monkeypatch.setattr(claude_code.shutil, "which", lambda name: name)
    assert claude_code.ClaudeCode({"befehl": "/opt/claude"}).befehl == "/opt/claude"


def test_fehlender_eigener_befehl_nimmt_claude_im_suchpfad(heim, monkeypatch):
    """Die Erkennung meldet dann „bereit“, also muss der Adapter dieselbe CLI aufrufen."""
    monkeypatch.setattr(claude_code.shutil, "which", lambda name: "/usr/bin/claude" if name == "claude" else None)
    assert claude_code.ClaudeCode({"befehl": "/weg/claude"}).befehl == "claude"


def test_fehlender_eigener_befehl_nutzt_installer_ort(heim):
    heim.write_text("", encoding="utf-8")
    assert claude_code.ClaudeCode({"befehl": "/weg/claude"}).befehl == str(heim)


def test_ohne_jede_cli_bleibt_der_eigene_befehl(heim):
    assert claude_code.ClaudeCode({"befehl": "/weg/claude"}).befehl == "/weg/claude"


def test_im_suchpfad_bleibt_der_befehl(heim, monkeypatch):
    heim.write_text("", encoding="utf-8")
    monkeypatch.setattr(claude_code.shutil, "which", lambda name: "/usr/bin/claude")
    assert claude_code.ClaudeCode({"befehl": "claude"}).befehl == "claude"
