"""Schnittstelle für KI-Modelle: text() für Transkripte, json() für strukturierte Inhalte."""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Protocol

PLATZHALTER = "{{bild_hinweis}}"


class ModellFehler(Exception):
    pass


class Modell(Protocol):
    name: str

    def text(self, prompt: str, bilder: list[Path]) -> str: ...

    def json(self, prompt: str, schema: dict, bilder: list[Path]) -> dict: ...


def bild_hinweis_einsetzen(prompt: str, hinweis: str) -> str:
    if PLATZHALTER in prompt:
        return prompt.replace(PLATZHALTER, hinweis)
    return (hinweis + "\n\n" + prompt) if hinweis else prompt


def anhang_hinweis(bilder: list[Path]) -> str:
    if not bilder:
        return ""
    namen = ", ".join(b.name for b in bilder)
    return f"Die Fotos sind in dieser Reihenfolge angehängt: {namen}."


def b64(pfad: Path) -> str:
    return base64.b64encode(pfad.read_bytes()).decode()


def json_aus_text(text: str) -> dict:
    """Fallback: JSON aus einer Textantwort holen (auch aus ```json-Blöcken)."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    else:
        a, b = text.find("{"), text.rfind("}")
        if a >= 0 and b > a:
            text = text[a:b + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ModellFehler(f"Antwort ist kein gültiges JSON: {e}") from e


def waehlen(name: str) -> Modell:
    from ..config import laden

    cfg = laden()
    if name == "claude_code":
        from .claude_code import ClaudeCode
        return ClaudeCode(cfg["claude_code"])
    if name == "gemini":
        from .gemini import Gemini
        return Gemini(cfg["gemini"])
    if name == "ollama":
        from .ollama import Ollama
        return Ollama(cfg["ollama"])
    raise ValueError(f"unbekanntes Modell {name!r}")
