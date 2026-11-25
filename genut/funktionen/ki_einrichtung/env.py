"""Gemini-Schlüssel in `.env` speichern (für `ki gemini-pruefen` und die Route, research.md R10).
Geschrieben wird dieselbe Datei, die `genut.modelle.gemini.schluessel()` liest."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from ...modelle import gemini as _gemini

MAX_LAENGE = 200
# sichtbare ASCII-Zeichen ohne " # ' – genau das, was `gemini.schluessel()` vollständig zurückliest
_ERLAUBT = re.compile(rf"""(?:(?!["'#])[!-~]){{1,{MAX_LAENGE}}}""")
_ZEILE = re.compile(r"\s*(?:export\s+)?(GEMINI_API_KEY|GOOGLE_API_KEY)\s*=")


def env_pfad() -> Path:
    return _gemini.WURZEL / ".env"


def schluessel_gueltig(schluessel: str) -> bool:
    """Taugt der Text als Schlüssel (Form, nicht ob Google ihn annimmt)?"""
    return _ERLAUBT.fullmatch(schluessel) is not None


def schluessel_speichern(schluessel: str) -> None:
    """Trägt `GEMINI_API_KEY=…` in `.env` ein (atomar, Rechte 0600); vorhandene Zeilen dafür werden ersetzt,
    alle anderen bleiben bytegleich. ValueError bei unbrauchbarer Form (die Meldung nennt den Schlüssel nie)."""
    if not schluessel_gueltig(schluessel):
        raise ValueError("Schlüssel hat eine unzulässige Form")
    pfad = env_pfad().resolve()  # ein Symlink bleibt erhalten
    text = pfad.read_bytes().decode("utf-8", "surrogateescape") if pfad.exists() else ""
    text = text.removeprefix("﻿")  # mit BOM würde die erste Zeile nicht gelesen
    ende = "\r\n" if "\r\n" in text else "\n"
    zeilen = re.findall(r"[^\n]*\n|[^\n]+$", text)
    treffer = {i: m[1] for i, z in enumerate(zeilen) if (m := _ZEILE.match(z))}
    eigene = [i for i, name in treffer.items() if name == "GEMINI_API_KEY"]
    neu = f"GEMINI_API_KEY={schluessel}"
    if treffer:
        # An die erste Schlüsselzeile: `gemini.schluessel()` nimmt die erste, auch GOOGLE_API_KEY.
        stelle = min(treffer)
        if stelle in eigene:
            alt = zeilen[stelle]
            zeilen[stelle] = neu + alt[len(alt.rstrip("\r\n")):]
        for i in reversed(eigene):
            if i != stelle:
                del zeilen[i]
        if stelle not in eigene:
            zeilen.insert(stelle, neu + ende)
    else:
        if zeilen and not zeilen[-1].endswith("\n"):
            zeilen[-1] += ende
        zeilen.append(neu + ende)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=pfad.parent, prefix=".env.")  # entsteht mit 0600
    try:
        with os.fdopen(fd, "wb") as f:
            f.write("".join(zeilen).encode("utf-8", "surrogateescape"))
        os.chmod(tmp, 0o600)
        os.replace(tmp, pfad)
    finally:
        Path(tmp).unlink(missing_ok=True)
