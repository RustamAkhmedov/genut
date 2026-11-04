"""Adapter für die Claude-Code-CLI (`claude -p`), läuft über das Abo des Nutzers.

Verifiziert mit Claude Code 2.1.x: Bei --output-format json und
--json-schema liegt das Ergebnis im Feld `structured_output`, der Text in `result`.
Bilder werden nicht angehängt, sondern per absolutem Pfad genannt und mit dem Read-Tool gelesen.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .base import ModellFehler, bild_hinweis_einsetzen, json_aus_text

TIMEOUT = 900


class ClaudeCode:
    name = "claude_code"

    def __init__(self, cfg: dict):
        self.befehl = cfg.get("befehl") or "claude"
        self.modell = cfg.get("modell") or ""

    def _hinweis(self, bilder: list[Path]) -> str:
        if not bilder:
            return ""
        zeilen = "\n".join(f"- {b.resolve()}" for b in bilder)
        return ("Lies zuerst diese Fotos (in dieser Reihenfolge) mit dem Read-Tool. "
                "Benutze sonst keine Werkzeuge.\n" + zeilen)

    def _aufruf(self, prompt: str, bilder: list[Path], schema: dict | None) -> dict:
        prompt = bild_hinweis_einsetzen(prompt, self._hinweis(bilder))
        cmd = [self.befehl, "-p", prompt, "--output-format", "json",
               # Fotos sind fremde Daten: keine schreibenden oder ausführenden Werkzeuge
               "--disallowedTools", "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch,Agent"]
        if bilder:
            cmd += ["--allowedTools", "Read"]
            for d in sorted({str(b.resolve().parent) for b in bilder}):
                cmd += ["--add-dir", d]
        if schema is not None:
            cmd += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
        if self.modell:
            cmd += ["--model", self.modell]
        cwd = bilder[0].resolve().parent if bilder else None
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT, cwd=cwd)
        except FileNotFoundError as e:
            raise ModellFehler(f"Claude-Code-CLI nicht gefunden ({self.befehl})") from e
        except subprocess.TimeoutExpired as e:
            raise ModellFehler(f"Claude Code hat nach {TIMEOUT} s nicht geantwortet") from e
        try:
            daten = json.loads(r.stdout)
        except json.JSONDecodeError as e:
            raise ModellFehler(f"Claude Code (Exit {r.returncode}): {(r.stderr or r.stdout)[-800:]}") from e
        if r.returncode != 0 or daten.get("is_error"):
            raise ModellFehler(f"Claude Code meldet Fehler: {str(daten.get('result') or r.stderr)[-800:]}")
        return daten

    def text(self, prompt: str, bilder: list[Path]) -> str:
        return (self._aufruf(prompt, bilder, None).get("result") or "").strip()

    def json(self, prompt: str, schema: dict, bilder: list[Path]) -> dict:
        daten = self._aufruf(prompt, bilder, schema)
        if isinstance(daten.get("structured_output"), dict):
            return daten["structured_output"]
        return json_aus_text(daten.get("result") or "")
