"""Erkennung der KIs (specs/005b-ein-genut/research.md R4, R5).

Geprüft werden nur `claude_code`, `gemini` und `ollama`, jede ohne Generierungsanfrage (SC-004) und mit
Zeitlimit. `zustaende()` prüft die KIs aus `[modell] auswahl` parallel und speichert jedes Ergebnis 15 s.
Ursachen sind feste kurze Texte: nie Pfade, nie Schlüssel, nie Fehlertexte von außen.

Die Einzelprüfungen (`claude_befehl`, `gemini_schluessel_pruefen`, `ollama_programm`, `ollama_modelle`, …)
sind öffentlich, damit Befehle (`python -m genut ki …`) und Routen dieselben Regeln nutzen.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal

import httpx

from ...config import laden
from ...modelle import gemini as _gemini
from .daten import KiZustand

GEPRUEFT = ("claude_code", "gemini", "ollama")
ZEITLIMIT = 5.0        # Sekunden je Prüfung
VERBINDUNGSZEIT = 1.0  # Sekunden für den Verbindungsaufbau zu Ollama
SPEICHERZEIT = 15.0    # Sekunden, die ein Ergebnis gilt
GEMINI_BASIS = _gemini.BASIS

# Ursachen (data-model.md KiZustand)
NICHT_ANGEMELDET = "nicht angemeldet"
KEINE_ANTWORT = "keine Antwort"
SCHLUESSEL_ABGELEHNT = "Schlüssel wird nicht akzeptiert"
KEINE_VERBINDUNG = "keine Verbindung"
OLLAMA_LAEUFT_NICHT = "Ollama läuft nicht"
PRUEFUNG_GESCHEITERT = "Prüfung fehlgeschlagen"

# Tests setzen hier einen `httpx.MockTransport` ein; None = echtes Netz.
transport: httpx.BaseTransport | None = None
_uhr: Callable[[], float] = time.monotonic

_sperre = threading.Lock()                      # schützt die drei Werte darunter
_speicher: dict[str, tuple[float, KiZustand]] = {}  # Name → (Zeit, Ergebnis)
_laufend: dict[str, threading.Event] = {}         # Name → Ereignis „Prüfung fertig“
_generation = 0                                   # zählt `leeren()`


def _windows() -> bool:
    return os.name == "nt"


def _client(timeout: httpx.Timeout | float) -> httpx.Client:
    return httpx.Client(transport=transport, timeout=timeout)


def _zustand(name: str, zustand: str, ursache: str = "", aktion: str = "") -> KiZustand:
    return KiZustand(name=name, zustand=zustand, ursache=ursache, aktion=aktion, geprueft=datetime.now())


# ---------------------------------------------------------------- Claude


def _claude_lokal() -> Path:
    """Ablage des offiziellen Installers."""
    if _windows():
        return Path(os.environ.get("USERPROFILE") or Path.home()) / ".local" / "bin" / "claude.exe"
    return Path.home() / ".local" / "bin" / "claude"


def claude_befehl(befehl: str | None = None) -> str | None:
    """Voller Pfad der Claude-CLI oder None. Reihenfolge: `befehl` (Standard: `[claude_code] befehl`),
    dann `claude` im PATH, dann `~/.local/bin/claude` (Windows: `%USERPROFILE%\\.local\\bin\\claude.exe`)."""
    if befehl is None:
        befehl = laden().get("claude_code", {}).get("befehl") or ""
    for kandidat in (str(befehl).strip(), "claude"):
        if kandidat and (gefunden := shutil.which(kandidat)):
            return gefunden
    lokal = _claude_lokal()
    if lokal.is_file() and (_windows() or os.access(lokal, os.X_OK)):
        return str(lokal)
    return None


def _json_objekt(text: str) -> dict | None:
    """Liest die Ausgabe tolerant: ganzes JSON oder das erste {...} darin."""
    text = (text or "").strip()
    for stueck in (text, text[text.find("{"): text.rfind("}") + 1] if "{" in text else ""):
        if not stueck:
            continue
        try:
            daten = json.loads(stueck)
        except ValueError:
            continue
        if isinstance(daten, dict):
            return daten
    return None


def claude_angemeldet(befehl: str) -> Literal["ja", "nein", "unbekannt", "keine_antwort", "fehlt"]:
    """`<befehl> auth status --json` (keine Anfrage an das Modell). Entscheidet am Inhalt, nicht am Exit-Code:
    `unbekannt` = keine lesbare Angabe (z. B. ältere CLI ohne den Befehl) → laut Rückfallregel bereit."""
    try:
        r = subprocess.run([befehl, "auth", "status", "--json"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=ZEITLIMIT, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return "keine_antwort"
    except OSError:
        return "fehlt"
    daten = _json_objekt(r.stdout)
    if daten is not None:
        for feld in ("loggedIn", "logged_in"):
            if daten.get(feld) is True:
                return "ja"
            if daten.get(feld) is False:
                return "nein"
    return "unbekannt"


def claude_pruefen(cfg: dict | None = None) -> KiZustand:
    cfg = cfg if cfg is not None else laden()
    befehl = claude_befehl(cfg.get("claude_code", {}).get("befehl") or "")
    if befehl is None:
        return _zustand("claude_code", "nicht_eingerichtet", "", "einrichten")
    ergebnis = claude_angemeldet(befehl)
    if ergebnis == "nein":
        return _zustand("claude_code", "problem", NICHT_ANGEMELDET, "anmelden")
    if ergebnis == "keine_antwort":
        return _zustand("claude_code", "problem", KEINE_ANTWORT)
    if ergebnis == "fehlt":
        return _zustand("claude_code", "nicht_eingerichtet", "", "einrichten")
    return _zustand("claude_code", "bereit")


# ---------------------------------------------------------------- Gemini


def gemini_schluessel_pruefen(schluessel: str, basis: str | None = None,
                              ) -> Literal["ok", "abgelehnt", "keine_verbindung"]:
    """Prüft einen (auch noch nicht gespeicherten) Schlüssel über die Modellliste, dieselbe Anfrage wie
    `Gemini._kandidaten()`, ohne Generierungskontingent. 400/401/403 → `abgelehnt`; Netzwerkfehler,
    Zeitüberschreitung und andere Antworten → `keine_verbindung`."""
    basis = (basis or GEMINI_BASIS).rstrip("/")
    try:
        with _client(ZEITLIMIT) as c:
            r = c.get(f"{basis}/models", params={"pageSize": 200}, headers={"x-goog-api-key": schluessel.strip()})
    except (httpx.HTTPError, ValueError):  # ValueError: Schlüssel mit unzulässigen Zeichen für eine Kopfzeile
        return "keine_verbindung"
    if r.status_code in (400, 401, 403):
        return "abgelehnt"
    return "ok" if r.is_success else "keine_verbindung"


def gemini_zustand(ergebnis: str) -> KiZustand:
    """KiZustand zum Ergebnis von `gemini_schluessel_pruefen` (auch für die Route nach dem Speichern)."""
    if ergebnis == "ok":
        return _zustand("gemini", "bereit")
    if ergebnis == "abgelehnt":
        return _zustand("gemini", "problem", SCHLUESSEL_ABGELEHNT, "schluessel")
    return _zustand("gemini", "problem", KEINE_VERBINDUNG)


def gemini_pruefen(cfg: dict | None = None) -> KiZustand:
    cfg = cfg if cfg is not None else laden()
    schluessel = _gemini.schluessel()
    if not schluessel:
        return _zustand("gemini", "nicht_eingerichtet", "", "schluessel")
    return gemini_zustand(gemini_schluessel_pruefen(schluessel, cfg.get("gemini", {}).get("basis_url")))


# ---------------------------------------------------------------- Ollama


def ollama_url(cfg: dict | None = None) -> str:
    cfg = cfg if cfg is not None else laden()
    return (cfg.get("ollama", {}).get("url") or "http://localhost:11434").rstrip("/")


def ollama_programm() -> str | None:
    """Pfad des Programms `ollama` (PATH, unter Windows auch `%LOCALAPPDATA%\\Programs\\Ollama`) oder None."""
    if gefunden := shutil.which("ollama"):
        return gefunden
    if _windows() and (lokal := os.environ.get("LOCALAPPDATA")):
        exe = Path(lokal) / "Programs" / "Ollama" / "ollama.exe"
        if exe.is_file():
            return str(exe)
    return None


def ollama_modelle(url: str | None = None) -> list[dict] | None:
    """Einträge aus `GET <url>/api/tags` (je Modell u. a. `name`, `size` in Byte) oder None, wenn Ollama
    nicht erreichbar ist oder unlesbar antwortet. Verbindungsaufbau höchstens 1 s."""
    url = (url or ollama_url()).rstrip("/")
    try:
        with _client(httpx.Timeout(ZEITLIMIT, connect=VERBINDUNGSZEIT)) as c:
            r = c.get(f"{url}/api/tags")
        r.raise_for_status()
        modelle = r.json().get("models", [])
    except (httpx.HTTPError, ValueError, AttributeError):
        return None
    return [m for m in modelle if isinstance(m, dict)] if isinstance(modelle, list) else None


def ollama_hat_modell(modelle: list[dict], modell: str) -> bool:
    """Ollama nennt Modelle mit Tag; `gemma3` meint `gemma3:latest`."""
    gesucht = {modell, f"{modell}:latest"} if ":" not in modell else {modell}
    return any(m.get("name") in gesucht or m.get("model") in gesucht for m in modelle)


def ollama_pruefen(cfg: dict | None = None) -> KiZustand:
    cfg = cfg if cfg is not None else laden()
    modell = (cfg.get("ollama", {}).get("modell") or "").strip()
    modelle = ollama_modelle(ollama_url(cfg))
    if modelle is None:
        if ollama_programm():
            return _zustand("ollama", "problem", OLLAMA_LAEUFT_NICHT, "starten")
        return _zustand("ollama", "nicht_eingerichtet", "", "einrichten")
    if not modell:
        return _zustand("ollama", "nicht_eingerichtet", "kein Modell gewählt", "einrichten")
    if not ollama_hat_modell(modelle, modell):
        return _zustand("ollama", "nicht_eingerichtet", f"Modell {modell} fehlt", "einrichten")
    return _zustand("ollama", "bereit")


# ---------------------------------------------------------------- Ablauf, Zwischenspeicher

_PRUEFUNGEN: dict[str, Callable[[dict], KiZustand]] = {
    "claude_code": claude_pruefen, "gemini": gemini_pruefen, "ollama": ollama_pruefen}
# Ergebnis, wenn eine Prüfung ihr Zeitlimit trotzdem überschreitet (z. B. hängende Namensauflösung)
_UEBERZEIT = {"claude_code": KEINE_ANTWORT, "gemini": KEINE_VERBINDUNG, "ollama": KEINE_ANTWORT}


def pruefen(name: str, cfg: dict | None = None) -> KiZustand:
    """Eine Prüfung ohne Zwischenspeicher und ohne Gesamtfrist."""
    return _PRUEFUNGEN[name](cfg if cfg is not None else laden())


def _parallel(namen: list[str], cfg: dict) -> dict[str, KiZustand]:
    """Prüft parallel in losgelösten Threads; wer nach der Frist nicht fertig ist, gilt als „keine Antwort“
    bzw. „keine Verbindung“ und blockiert niemanden (der Thread läuft im Hintergrund aus)."""
    ergebnisse: dict[str, KiZustand] = {}

    def lauf(name: str) -> None:
        try:
            ergebnisse[name] = pruefen(name, cfg)
        except Exception:
            ergebnisse[name] = _zustand(name, "problem", PRUEFUNG_GESCHEITERT)

    threads = [threading.Thread(target=lauf, args=(n,), daemon=True, name=f"ki-erkennung-{n}") for n in namen]
    for t in threads:
        t.start()
    frist = time.monotonic() + ZEITLIMIT + 0.5
    for t in threads:
        t.join(max(0.0, frist - time.monotonic()))
    return {n: ergebnisse.get(n) or _zustand(n, "problem", _UEBERZEIT[n]) for n in namen}


def _namen(cfg: dict) -> list[str]:
    auswahl = cfg.get("modell", {}).get("auswahl") or []
    return list(dict.fromkeys(n for n in auswahl if n in GEPRUEFT))


def _holen(namen: list[str], neu: bool) -> dict[str, KiZustand]:
    """Gespeicherte Ergebnisse nehmen, fehlende prüfen. Läuft für eine KI schon eine Prüfung (anderer
    Aufrufer), wird auf deren Ergebnis gewartet statt doppelt zu prüfen."""
    with _sperre:
        jetzt = _uhr()
        fertig = {} if neu else {n: e[1] for n in namen
                                 if (e := _speicher.get(n)) is not None and jetzt - e[0] < SPEICHERZEIT}
        offen = [n for n in namen if n not in fertig]
        eigene = [n for n in offen if n not in _laufend]
        fremde = {n: _laufend[n] for n in offen if n in _laufend}
        for n in eigene:
            _laufend[n] = threading.Event()
        generation = _generation
    if eigene:
        neue: dict[str, KiZustand] = {}
        try:
            neue = _parallel(eigene, laden())
        finally:
            with _sperre:
                if generation == _generation:  # nach `leeren()` nichts Altes speichern
                    for n, z in neue.items():
                        _speicher[n] = (_uhr(), z)
                for n in eigene:
                    _laufend.pop(n).set()
        fertig.update(neue)
    for n, ereignis in fremde.items():
        ereignis.wait(ZEITLIMIT + 1)
        with _sperre:
            eintrag = _speicher.get(n)
        fertig[n] = eintrag[1] if eintrag else _zustand(n, "problem", _UEBERZEIT[n])
    return fertig


def zustaende(neu: bool = False) -> list[KiZustand]:
    """Zustände der bekannten KIs aus `[modell] auswahl` in deren Reihenfolge; andere Namen werden übersprungen.
    Ergebnisse gelten 15 s; `neu=True` umgeht den Speicher."""
    namen = _namen(laden())
    ergebnisse = _holen(namen, neu)
    return [ergebnisse[n] for n in namen]


def zustand(name: str, neu: bool = False) -> KiZustand | None:
    """Zustand einer KI (auch wenn sie nicht in `auswahl` steht); None für unbekannte Namen."""
    if name not in GEPRUEFT:
        return None
    return _holen([name], neu)[name]


def bereit(name: str) -> bool | None:
    """Ist die KI bereit? None = unbekannt (Name wird nicht geprüft, z. B. `openai_kompatibel`)."""
    z = zustand(name)
    return None if z is None else z.zustand == "bereit"


def leeren() -> None:
    """Vergisst alle gespeicherten Ergebnisse (nach Einrichtung oder Änderung der Konfiguration)."""
    global _generation
    with _sperre:
        _speicher.clear()
        _generation += 1


def erste_pruefung() -> None:
    """Erste Erkennung nach dem Serverstart; läuft in einem eigenen Thread."""
    try:
        zustaende(neu=True)
    except Exception:
        pass
