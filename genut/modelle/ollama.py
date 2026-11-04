"""Adapter für ein lokales Modell über Ollama (/api/chat mit images und format=Schema)."""
from __future__ import annotations

from pathlib import Path

import httpx

from .base import ModellFehler, anhang_hinweis, b64, bild_hinweis_einsetzen, json_aus_text

TIMEOUT = 1800


class Ollama:
    name = "ollama"

    def __init__(self, cfg: dict):
        self.url = (cfg.get("url") or "http://localhost:11434").rstrip("/") + "/api/chat"
        self.modell = cfg.get("modell") or "gemma3:4b"

    def _aufruf(self, prompt: str, bilder: list[Path], schema: dict | None) -> str:
        msg = {"role": "user", "content": bild_hinweis_einsetzen(prompt, anhang_hinweis(bilder))}
        if bilder:
            msg["images"] = [b64(b) for b in bilder]
        body = {"model": self.modell, "stream": False, "messages": [msg], "options": {"temperature": 0.2, "num_ctx": 16384}}
        if schema is not None:
            body["format"] = schema
        try:
            r = httpx.post(self.url, json=body, timeout=TIMEOUT)
        except httpx.HTTPError as e:
            raise ModellFehler(f"Ollama nicht erreichbar ({self.url}): {e}") from e
        if r.status_code >= 400:
            raise ModellFehler(f"Ollama HTTP {r.status_code}: {r.text[:600]}")
        return r.json().get("message", {}).get("content", "")

    def text(self, prompt: str, bilder: list[Path]) -> str:
        return self._aufruf(prompt, bilder, None).strip()

    def json(self, prompt: str, schema: dict, bilder: list[Path]) -> dict:
        return json_aus_text(self._aufruf(prompt, bilder, schema))
