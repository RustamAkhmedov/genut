"""Lädt config.toml aus dem Projektwurzelordner."""
from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
PAKET = Path(__file__).resolve().parent

STANDARD = {
    "server": {"host": "127.0.0.1", "port": 8765},
    "modell": {"standard": "claude_code", "auswahl": ["claude_code", "gemini"]},
    "claude_code": {"befehl": "claude", "modell": ""},
    "gemini": {"modell": ""},
    "ollama": {"url": "http://localhost:11434", "modell": "gemma3:4b"},
    "pages": {"aktiv": False, "repo_pfad": "", "basis_url": ""},
}


def config_pfad() -> Path:
    return Path(os.environ.get("GENUT_CONFIG", WURZEL / "config.toml"))


@lru_cache
def laden() -> dict:
    pfad = config_pfad()
    daten = tomllib.loads(pfad.read_text(encoding="utf-8")) if pfad.exists() else {}
    cfg = {k: dict(v) for k, v in STANDARD.items()}
    for abschnitt, werte in daten.items():
        cfg.setdefault(abschnitt, {}).update(werte)
    return cfg


def node_befehl() -> str:
    """Node.js: GENUT_NODE, sonst die vom Setup mitgebrachte Version in .werkzeuge/node, sonst `node` aus dem PATH."""
    if os.environ.get("GENUT_NODE"):
        return os.environ["GENUT_NODE"]
    for kandidat in (WURZEL / ".werkzeuge" / "node" / "bin" / "node", WURZEL / ".werkzeuge" / "node" / "node.exe"):
        if kandidat.exists():
            return str(kandidat)
    return "node"


def projekte_ordner() -> Path:
    return Path(os.environ.get("GENUT_PROJEKTE", WURZEL / "projekte"))
