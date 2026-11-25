"""KIs aus der Oberfläche einrichten (specs/005b-ein-genut/research.md R8 bis R10, contracts/api.md).

Gemini wird sofort erledigt (Schlüssel prüfen und speichern). Alles, was länger dauert, läuft als
Einrichtungsauftrag in einem eigenen Thread: Claude installieren, ein Ollama-Modell laden, Ollama starten.
Aufträge liegen nur im Speicher, je KI läuft höchstens einer, fertige bleiben 10 Minuten abrufbar.
Nach jedem Auftrag wird der Zwischenspeicher der Erkennung geleert, bevor der Auftrag als beendet gilt:
wer danach die Zustände abfragt, bekommt eine frische Prüfung (SC-003).

Kein Text eines Auftrags und keine Antwort enthält einen Schlüssel (SC-005). Installiert wird nur von
claude.ai (R10); Ollama selbst installiert nur das Setup (FR-018).

Testhaken: `_popen` (Unterprozesse), `_schlafen`, `_uhr`; Netz über `erkennung.transport`.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from urllib.parse import urlsplit

import httpx

from ...config import laden, wert_setzen
from . import daten, env, erkennung, modellwahl, rechner
from .daten import Einrichtungsauftrag, KiZustand

HALTEZEIT = 600.0        # Sekunden, die ein beendeter Auftrag abrufbar bleibt
INSTALLER_FRIST = 900.0  # Sekunden, dann wird der Installer beendet
STARTFRIST = 10.0        # Sekunden, die nach `ollama serve` auf /api/tags gewartet wird
LESEZEIT = 120.0         # Sekunden ohne neue Zeile von Ollama, dann gilt der Download als abgebrochen
MELDUNG_MAX = 300
NAME_MAX = 200
_GIB = 1024 ** 3

CLAUDE_INSTALLER_SH = "https://claude.ai/install.sh"
CLAUDE_INSTALLER_PS1 = "https://claude.ai/install.ps1"
_TITEL = {"claude_code": "Claude", "gemini": "Gemini", "ollama": "Lokal"}

# Testhaken
_popen: Callable[..., subprocess.Popen] = subprocess.Popen
_schlafen: Callable[[float], None] = time.sleep
_uhr: Callable[[], float] = time.monotonic


class Fehler(Exception):
    """Abgelehnte Anfrage: die Route antwortet mit `status` und `meldung` als `detail`."""

    def __init__(self, status: int, meldung: str):
        super().__init__(meldung)
        self.status, self.meldung = status, meldung


class AuftragFehler(Exception):
    """Ein Auftrag scheitert; die Meldung (ohne Schlüssel, ohne Pfade) landet im Auftrag."""


# ---------------------------------------------------------------- Aufträge


@dataclass
class _Eintrag:
    auftrag: Einrichtungsauftrag
    ende: float | None = None  # `_uhr()` beim Beenden


_sperre = threading.Lock()
_auftraege: dict[str, _Eintrag] = {}


def _aufraeumen() -> None:
    """Vergisst beendete Aufträge nach HALTEZEIT. Nur mit `_sperre` aufrufen."""
    jetzt = _uhr()
    for kennung in [k for k, e in _auftraege.items() if e.ende is not None and jetzt - e.ende > HALTEZEIT]:
        del _auftraege[kennung]


def laufend(ki: str) -> str | None:
    """Kennung des laufenden Auftrags dieser KI oder None."""
    with _sperre:
        return next((k for k, e in _auftraege.items() if e.auftrag.ki == ki and e.auftrag.status == "laeuft"), None)


def auftrag(kennung: str) -> Einrichtungsauftrag | None:
    """Kopie des Auftrags oder None (unbekannt oder schon vergessen)."""
    with _sperre:
        _aufraeumen()
        eintrag = _auftraege.get(kennung)
        return eintrag.auftrag.model_copy() if eintrag else None


def mit_auftrag(z: KiZustand) -> KiZustand:
    """Trägt die Kennung eines laufenden Auftrags ein, egal in welchem Zustand die KI gerade ist (während
    einer Installation kann Claude schon „problem“ sein, während eines Downloads Lokal noch „bereit“)."""
    return z.model_copy(update={"auftrag": laufend(z.name)})


def vergessen() -> None:
    """Nur für Tests: alle Aufträge vergessen (laufende Threads schreiben dann ins Leere)."""
    with _sperre:
        _auftraege.clear()


_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-_]")
_STEUER = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _saeubern(text: str) -> str:
    """Eine Ausgabezeile lesbar machen: Farbcodes weg, bei Fortschrittszeilen mit \\r das letzte Stück."""
    text = _ANSI.sub("", str(text))
    text = next((t for t in reversed(text.split("\r")) if t.strip()), "")
    text = " ".join(_STEUER.sub("", text).split())
    return text if len(text) <= MELDUNG_MAX else text[: MELDUNG_MAX - 1] + "…"


def _melden(kennung: str, meldung: str | None = None, fortschritt: int | None = None) -> None:
    with _sperre:
        eintrag = _auftraege.get(kennung)
        if eintrag is None or eintrag.auftrag.status != "laeuft":
            return
        if meldung is not None and (text := _saeubern(meldung)):
            eintrag.auftrag.meldung = text
        if fortschritt is not None:
            eintrag.auftrag.fortschritt = max(0, min(100, int(fortschritt)))


def _beenden(kennung: str, status: str, meldung: str) -> None:
    with _sperre:
        eintrag = _auftraege.get(kennung)
        if eintrag is None:
            return
        a = eintrag.auftrag
        a.status, a.beendet = status, datetime.now()
        a.meldung = _saeubern(meldung) or a.meldung
        if status == "fertig" and a.fortschritt is not None:
            a.fortschritt = 100
        eintrag.ende = _uhr()


Melden = Callable[..., None]  # melden(meldung=None, fortschritt=None)


def _lauf(kennung: str, arbeit: Callable[[Melden], str]) -> None:
    try:
        meldung = arbeit(lambda meldung=None, fortschritt=None: _melden(kennung, meldung, fortschritt))
        status = "fertig"
    except AuftragFehler as e:
        meldung, status = str(e), "fehler"
    except Exception:  # nie einen fremden Fehlertext zeigen: er könnte Pfade enthalten
        meldung, status = "Unerwarteter Fehler bei der Einrichtung", "fehler"
    # Erst leeren, dann beenden: wer „fertig“ sieht und neu abfragt, bekommt keinen alten Zustand.
    erkennung.leeren()
    _beenden(kennung, status, meldung)


def starten(ki: str, schritt: str, arbeit: Callable[[Melden], str]) -> str:
    """Legt einen Auftrag an und startet `arbeit(melden)` in einem Thread. `arbeit` liefert die
    Schlussmeldung oder wirft AuftragFehler. Fehler(409), wenn für die KI schon einer läuft."""
    with _sperre:
        _aufraeumen()
        if any(e.auftrag.ki == ki and e.auftrag.status == "laeuft" for e in _auftraege.values()):
            raise Fehler(409, f"Für {_TITEL[ki]} läuft schon eine Einrichtung")
        while (kennung := f"ke-{secrets.token_hex(4)}") in _auftraege:
            pass
        _auftraege[kennung] = _Eintrag(Einrichtungsauftrag(
            id=kennung, ki=ki, schritt=schritt, status="laeuft", gestartet=datetime.now()))
    threading.Thread(target=_lauf, args=(kennung, arbeit), daemon=True, name=f"ki-einrichten-{ki}").start()
    return kennung


def _nicht_laufend(ki: str) -> None:
    if laufend(ki):
        raise Fehler(409, f"Für {_TITEL[ki]} läuft schon eine Einrichtung")


# ---------------------------------------------------------------- Gemini


def gemini_schluessel(roh: object) -> KiZustand:
    """Prüft den Schlüssel bei Google und speichert ihn nur bei Erfolg in `.env` (R10). Danach gilt er
    auch im laufenden Server (Umgebungsvariable) und die Erkennung prüft neu."""
    if not isinstance(roh, str) or not (schluessel := "".join(roh.split())):
        raise Fehler(400, "Bitte gib einen Schlüssel ein")
    if not env.schluessel_gueltig(schluessel):  # auch: länger als 200 Zeichen
        raise Fehler(400, erkennung.SCHLUESSEL_ABGELEHNT)
    ergebnis = erkennung.gemini_schluessel_pruefen(schluessel, laden().get("gemini", {}).get("basis_url"))
    if ergebnis == "abgelehnt":
        raise Fehler(400, erkennung.SCHLUESSEL_ABGELEHNT)
    if ergebnis != "ok":
        raise Fehler(503, "Keine Verbindung zu Google. Nichts gespeichert.")
    try:
        env.schluessel_speichern(schluessel)
    except (OSError, ValueError):
        raise Fehler(500, "Der Schlüssel funktioniert, ließ sich aber nicht in .env speichern") from None
    # `gemini.schluessel()` liest zuerst die Umgebung: ein alter Wert dort würde sonst weiter gelten.
    os.environ["GEMINI_API_KEY"] = schluessel
    erkennung.leeren()
    return erkennung.gemini_zustand("ok")


# ---------------------------------------------------------------- Claude


def _installer_befehl() -> list[str]:
    """Offizieller Installer (R8): installiert ohne Admin-Rechte nach ~/.local/bin."""
    if erkennung._windows():
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                f"irm {CLAUDE_INSTALLER_PS1} | iex"]
    return ["bash", "-c",
            "set -o pipefail; if command -v curl >/dev/null 2>&1; "
            f"then curl -fsSL {CLAUDE_INSTALLER_SH}; else wget -qO- {CLAUDE_INSTALLER_SH}; fi | bash"]


def _claude_pfad_eintragen(pfad: str) -> None:
    """Der Adapter ruft `[claude_code] befehl` auf. Findet der Server diesen Befehl nicht (typisch: frisch
    nach ~/.local/bin installiert, das nicht im PATH des Servers liegt), wird der volle Pfad eingetragen."""
    konfiguriert = str(laden().get("claude_code", {}).get("befehl") or "claude").strip()
    if shutil.which(konfiguriert) is None:
        wert_setzen("claude_code", "befehl", pfad)


def _claude_installieren(melden: Melden) -> str:
    melden("Lade den Installer von claude.ai …")
    try:
        p = _popen(_installer_befehl(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                   stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                   env={**os.environ, "NO_COLOR": "1"})
    except OSError:
        raise AuftragFehler("Der Installer ließ sich nicht starten") from None
    wecker = threading.Timer(INSTALLER_FRIST, p.kill)
    wecker.daemon = True
    wecker.start()
    letzte = ""
    try:
        for zeile in p.stdout:
            if text := _saeubern(zeile):
                letzte = text
                melden(text)
        code = p.wait()
    finally:
        wecker.cancel()
    if code != 0:
        raise AuftragFehler(f"Installation fehlgeschlagen: {letzte}" if letzte else "Installation fehlgeschlagen")
    pfad = erkennung.claude_befehl()
    if pfad is None:
        raise AuftragFehler("Claude Code wurde nach der Installation nicht gefunden")
    try:
        _claude_pfad_eintragen(pfad)
    except ValueError:
        raise AuftragFehler("Claude ist installiert, aber der Pfad ließ sich nicht in config.toml eintragen") from None
    return "Claude Code ist installiert. Melde dich jetzt im Terminal an."


def claude_installieren() -> str:
    _nicht_laufend("claude_code")
    if erkennung.claude_befehl():
        raise Fehler(409, "Claude Code ist schon installiert")
    return starten("claude_code", "installieren", _claude_installieren)


# ---------------------------------------------------------------- Ollama


def _tags_oder_503(url: str) -> list[dict]:
    tags = erkennung.ollama_modelle(url)
    if tags is None:
        raise Fehler(503, "Ollama ist nicht erreichbar")
    return tags


def _tag_name(m: dict) -> str:
    return str(m.get("name") or m.get("model") or "")


def versteht_bilder(url: str, name: str) -> bool:
    """`POST /api/show`: `capabilities` enthält `vision` (R9). Ohne diese Angabe: nein."""
    try:
        with erkennung._client(httpx.Timeout(erkennung.ZEITLIMIT, connect=erkennung.VERBINDUNGSZEIT)) as c:
            r = c.post(f"{url}/api/show", json={"model": name})
        r.raise_for_status()
        faehigkeiten = r.json().get("capabilities")
    except (httpx.HTTPError, ValueError, AttributeError):
        return False
    return isinstance(faehigkeiten, list) and "vision" in faehigkeiten


def _vorschlagsnamen() -> list[str]:
    return [m.name for m in daten.modelle_laden()]


def _ist_vorschlag(tag: str, vorschlaege: list[str]) -> bool:
    return any(erkennung.ollama_hat_modell([{"name": tag}], v) for v in vorschlaege)


def vorhandene_mit_bildern(url: str, tags: list[dict]) -> list[dict]:
    """Geladene Modelle mit Bildverständnis, die keine Vorschläge sind (die zeigt die Liste als
    „schon geladen“), in der Reihenfolge von Ollama."""
    vorschlaege = _vorschlagsnamen()
    kandidaten = [m for m in tags if _tag_name(m) and not _ist_vorschlag(_tag_name(m), vorschlaege)]
    if not kandidaten:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(kandidaten))) as pool:
        bilder = list(pool.map(lambda m: versteht_bilder(url, _tag_name(m)), kandidaten))
    return [m for m, ja in zip(kandidaten, bilder) if ja]


def _groesse_gb(m: dict) -> float:
    groesse = m.get("size")
    return round(groesse / _GIB, 1) if isinstance(groesse, (int, float)) and groesse > 0 else 0.0


def ollama_vorschlaege() -> dict:
    url = erkennung.ollama_url()
    tags = _tags_oder_503(url)
    profil = rechner.profil()
    geladen = [n for n in _vorschlagsnamen() if erkennung.ollama_hat_modell(tags, n)]
    liste = modellwahl.vorschlaege(profil, geladen)
    return {
        "profil": profil.model_dump(include={"ram_gb", "grafik", "grafik_gb", "frei_gb"}),
        "vorschlaege": [v.model_dump() for v in liste],
        "vorhanden": [{"name": _tag_name(m), "groesse_gb": _groesse_gb(m)}
                      for m in vorhandene_mit_bildern(url, tags)],
        "keins_gut": modellwahl.keins_gut(liste),
    }


def _modell_setzen(name: str) -> None:
    try:
        wert_setzen("ollama", "modell", name)
    except ValueError:
        raise AuftragFehler("Das Modell ließ sich nicht in config.toml eintragen") from None


def _gb(wert: float) -> str:
    return f"{wert / _GIB:.1f}".replace(".", ",")


def _laden(url: str, name: str, melden: Melden) -> str:
    """`POST /api/pull` mit `stream: true` (R9). Der Fortschritt summiert `completed/total` über alle
    Teile (je `digest`) und fällt nie, auch wenn ein neuer Teil die Gesamtgröße erhöht."""
    melden(f"Lade {name} herunter …", 0)
    teile: dict[str, tuple[float, float]] = {}
    bisher, fertig = 0, False
    zeit = httpx.Timeout(LESEZEIT, connect=erkennung.ZEITLIMIT)
    try:
        with erkennung._client(zeit) as c, c.stream(
                "POST", f"{url}/api/pull", json={"model": name, "stream": True}) as r:
            if r.status_code != 200:
                raise AuftragFehler(f"Download abgebrochen: Ollama antwortet mit Fehler {r.status_code}")
            for zeile in r.iter_lines():
                try:
                    obj = json.loads(zeile) if zeile.strip() else None
                except ValueError:
                    obj = None
                if not isinstance(obj, dict):
                    continue
                if obj.get("error"):
                    raise AuftragFehler(f"Download abgebrochen: {_saeubern(obj['error'])}")
                if obj.get("status") == "success":
                    fertig = True
                    continue
                gesamt, erledigt = obj.get("total"), obj.get("completed") or 0
                if isinstance(gesamt, (int, float)) and gesamt > 0 and isinstance(erledigt, (int, float)):
                    teile[str(obj.get("digest") or obj.get("status") or "")] = (min(erledigt, gesamt), gesamt)
                    summe_e, summe_g = sum(t[0] for t in teile.values()), sum(t[1] for t in teile.values())
                    bisher = max(bisher, min(99, int(summe_e * 100 / summe_g)))
                    melden(f"Lade {name}: {_gb(summe_e)} von {_gb(summe_g)} GB", bisher)
    except httpx.HTTPError:
        raise AuftragFehler("Download abgebrochen: die Verbindung zu Ollama ist abgerissen") from None
    if not fertig:
        raise AuftragFehler("Download abgebrochen")
    _modell_setzen(name)
    melden(fortschritt=100)
    return f"{name} ist geladen und eingestellt"


def ollama_modell(roh: object) -> KiZustand | str:
    """Wählt ein Modell: ein Vorschlag oder ein geladenes Modell mit Bildverständnis. Ist es schon geladen,
    wird es sofort eingestellt (Rückgabe KiZustand), sonst startet der Download (Rückgabe Auftragskennung)."""
    name = roh.strip() if isinstance(roh, str) else ""
    if not name or len(name) > NAME_MAX:
        raise Fehler(400, "Unbekanntes Modell")
    _nicht_laufend("ollama")
    url = erkennung.ollama_url()
    tags = _tags_oder_503(url)
    if name not in _vorschlagsnamen():
        treffer = [_tag_name(m) for m in vorhandene_mit_bildern(url, tags)
                   if erkennung.ollama_hat_modell([m], name)]
        if not treffer:
            raise Fehler(400, "Unbekanntes Modell")
        name = treffer[0]
    if erkennung.ollama_hat_modell(tags, name):
        try:
            _modell_setzen(name)
        except AuftragFehler as e:
            raise Fehler(500, str(e)) from None
        erkennung.leeren()
        return mit_auftrag(erkennung.zustand("ollama", neu=True))
    return starten("ollama", "herunterladen", lambda melden: _laden(url, name, melden))


def _serve_umgebung(url: str) -> dict[str, str]:
    """Steht in config.toml ein anderer lokaler Port als 11434, soll `ollama serve` dort lauschen."""
    umgebung = dict(os.environ)
    teile = urlsplit(url)
    if teile.hostname in ("localhost", "127.0.0.1") and teile.port and teile.port != 11434:
        umgebung["OLLAMA_HOST"] = f"{teile.hostname}:{teile.port}"
    return umgebung


def _ollama_starten(programm: str, url: str, melden: Melden) -> str:
    """`ollama serve` losgelöst vom Server (wie `nohup … &` in setup.sh), dann bis zu 10 s warten."""
    melden("Starte Ollama …")
    kw: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                "env": _serve_umgebung(url)}
    if erkennung._windows():
        kw["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", 0x8)
                               | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200))
    else:
        kw["start_new_session"] = True  # Strg+C am Server beendet Ollama nicht
    try:
        _popen([programm, "serve"], **kw)
    except OSError:
        raise AuftragFehler("Ollama ließ sich nicht starten") from None
    ende = _uhr() + STARTFRIST
    while erkennung.ollama_modelle(url) is None:
        if _uhr() >= ende:
            raise AuftragFehler("Ollama antwortet nach dem Start nicht")
        _schlafen(0.5)
    return "Ollama läuft"


def ollama_starten() -> str:
    programm = erkennung.ollama_programm()
    if not programm:
        raise Fehler(404, "Ollama ist nicht installiert")
    _nicht_laufend("ollama")
    url = erkennung.ollama_url()
    if erkennung.ollama_modelle(url) is not None:
        erkennung.leeren()  # der gespeicherte Zustand „läuft nicht“ ist veraltet
        raise Fehler(409, "Ollama läuft schon")
    return starten("ollama", "starten", lambda melden: _ollama_starten(programm, url, melden))
