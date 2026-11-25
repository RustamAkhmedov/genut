"""Lädt config.toml aus dem Projektwurzelordner."""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
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
    "funktionen": {"lernplan": True, "pruefung": "auto", "ki_einrichtung": True, "austausch": True},
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


def _wert_toml(wert: str | list[str]) -> str:
    # JSON-Zeichenketten sind gültige TOML-Zeichenketten
    if isinstance(wert, list):
        return "[" + ", ".join(_wert_toml(w) for w in wert) + "]"
    return json.dumps(wert, ensure_ascii=False)


def _als_toml(text: str) -> dict | None:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None


def _kommentar(zuweisung: str) -> str:
    """Leerraum und Kommentar hinter dem Wert einer vollständigen Zuweisung (sonst leer)."""
    zuweisung = zuweisung.rstrip("\r\n")
    ganz = _als_toml(zuweisung)
    for treffer in re.finditer("#", zuweisung):
        davor = zuweisung[: treffer.start()]
        if _als_toml(davor) == ganz:  # dieses # steht nicht im Wert
            return zuweisung[len(davor.rstrip()):]
    return ""


def _ersetzt(text: str, abschnitt: str, schluessel: str, wert: str) -> str:
    """`text` mit `schluessel = wert` im Abschnitt; alle anderen Zeilen bleiben unverändert."""
    ende_zeichen = "\r\n" if "\r\n" in text else "\n"
    zeilen = re.findall(r"[^\n]*\n|[^\n]+$", text)
    name = re.escape(schluessel)
    zuweisung = f"{schluessel} = {wert}"
    im_abschnitt, einfuegen, i = False, None, 0
    while i < len(zeilen):
        kopf = re.match(r"\s*(\[\[?)\s*([^\[\]=]+?)\s*\]\]?\s*(#.*)?$", zeilen[i].rstrip("\r\n"))
        if kopf:
            im_abschnitt = kopf[1] == "[" and kopf[2] == abschnitt
            i += 1
            if im_abschnitt:
                einfuegen = i
            continue
        if "=" not in zeilen[i] or zeilen[i].lstrip().startswith("#"):
            i += 1
            continue
        # ein Wert kann über mehrere Zeilen gehen (Listen, mehrzeilige Zeichenketten)
        ende = i + 1
        while ende < len(zeilen) and _als_toml("".join(zeilen[i:ende])) is None:
            ende += 1
        if im_abschnitt:
            treffer = re.match(rf"""(\s*(?:{name}|"{name}"|'{name}')\s*=\s*)""", zeilen[i])
            if treffer:
                alt = "".join(zeilen[i:ende])
                zeilenende = alt[len(alt.rstrip("\r\n")):]
                zeilen[i:ende] = [treffer[1] + wert + _kommentar(alt) + zeilenende]
                return "".join(zeilen)
            einfuegen = ende
        i = ende
    if einfuegen is None:  # Abschnitt fehlt
        if text and not text.endswith("\n"):
            text += ende_zeichen
        if text:
            text += ende_zeichen
        return f"{text}[{abschnitt}]{ende_zeichen}{zuweisung}{ende_zeichen}"
    if not zeilen[einfuegen - 1].endswith("\n"):
        zeilen[einfuegen - 1] += ende_zeichen
    zeilen.insert(einfuegen, zuweisung + ende_zeichen)
    return "".join(zeilen)


_schreibsperre = threading.Lock()  # Einrichtungsaufträge laufen in Threads und schreiben gleichzeitig


def wert_setzen(abschnitt: str, schluessel: str, wert: str | list[str]) -> None:
    """Einen Wert in config.toml schreiben (atomar), Kommentare und andere Zeilen bleiben bytegleich."""
    with _schreibsperre:  # Lesen, Ändern, Schreiben am Stück: sonst ginge eine gleichzeitige Änderung verloren
        _wert_setzen(abschnitt, schluessel, wert)


def _wert_setzen(abschnitt: str, schluessel: str, wert: str | list[str]) -> None:
    pfad = config_pfad().resolve()  # ein Symlink bleibt erhalten
    text = pfad.read_bytes().decode("utf-8") if pfad.exists() else ""
    neu = _ersetzt(text, abschnitt, schluessel, _wert_toml(wert))
    # Schreibweisen wie `modell = { … }` kann _ersetzt nicht ändern: dann lieber nichts schreiben
    if (_als_toml(neu) or {}).get(abschnitt, {}).get(schluessel) != wert:
        raise ValueError(f"[{abschnitt}] {schluessel} lässt sich in {pfad.name} nicht automatisch ändern")
    pfad.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=pfad.parent, prefix=f".{pfad.name}.")
    try:
        with os.fdopen(fd, "wb") as f:  # binär: Zeilenenden nicht umwandeln
            f.write(neu.encode("utf-8"))
        if pfad.exists():
            shutil.copymode(pfad, tmp)
        os.replace(tmp, pfad)
    finally:
        Path(tmp).unlink(missing_ok=True)
    laden.cache_clear()


def auswahl_ergaenzen() -> list[str]:
    """Fehlende KIs hinten an [modell] auswahl anhängen (vorher config.toml.bak). Liefert die ergänzten."""
    laden.cache_clear()
    auswahl = list(laden()["modell"].get("auswahl") or [])
    fehlend = [ki for ki in ("claude_code", "gemini", "ollama") if ki not in auswahl]
    if fehlend:
        pfad = config_pfad()
        if pfad.exists():
            shutil.copy(pfad, pfad.with_name(pfad.name + ".bak"))
        wert_setzen("modell", "auswahl", auswahl + fehlend)
    return fehlend


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
