"""HTTP-Routen /api/ki/… (specs/005b-ein-genut/contracts/api.md). Der Schalter wird von der gemeinsamen
Abhängigkeit aus `genut.funktionen` je Anfrage geprüft (aus → 404).

Jede schreibende Route braucht `dependencies=[Depends(schreibschutz)]` aus `genut.schutz` (research.md R10).
Fehler kommen als `{"detail": "<deutsche Meldung>"}`.

Antwortformate (für die Oberfläche):

- `GET  /api/ki/zustaende?neu=0|1` → `{"zustaende": [KiZustand], "keine_bereit": bool}`.
  KiZustand = `{"name", "zustand", "ursache", "aktion", "geprueft", "auftrag"}`; `auftrag` ist die Kennung
  eines laufenden Einrichtungsauftrags dieser KI oder `null`, unabhängig vom Zustand (auch bei „bereit“).
- `POST /api/ki/gemini/schluessel` `{"schluessel": "…"}` → 200 KiZustand (Gemini, „bereit“);
  400 „Bitte gib einen Schlüssel ein“ bzw. „Schlüssel wird nicht akzeptiert“ (`.env` unverändert),
  503 „Keine Verbindung zu Google. Nichts gespeichert.“
- `POST /api/ki/claude/installieren` → 202 `{"auftrag": "ke-…"}`; 409 „Claude Code ist schon installiert“ bzw.
  „Für Claude läuft schon eine Einrichtung“.
- `GET  /api/ki/ollama/vorschlaege` → `{"profil": {"ram_gb", "grafik", "grafik_gb", "frei_gb"},
  "vorschlaege": [Modellvorschlag ×3], "vorhanden": [{"name", "groesse_gb"}], "keins_gut": bool}`;
  503 „Ollama ist nicht erreichbar“. `vorhanden` = geladene Modelle mit Bildverständnis außer den Vorschlägen
  (ein geladener Vorschlag hat `"vorhanden": true`).
- `POST /api/ki/ollama/modell` `{"name": "…"}` → 202 `{"auftrag": "ke-…"}` (Download) oder 200 KiZustand
  (schon geladen, sofort eingestellt); 400 „Unbekanntes Modell“, 409 „Für Lokal läuft schon eine Einrichtung“,
  503 „Ollama ist nicht erreichbar“.
- `POST /api/ki/ollama/starten` → 202 `{"auftrag": "ke-…"}`; 404 „Ollama ist nicht installiert“,
  409 „Ollama läuft schon“ bzw. „Für Lokal läuft schon eine Einrichtung“.
- `GET  /api/ki/auftraege/{id}` → Einrichtungsauftrag `{"id", "ki", "schritt", "status", "fortschritt",
  "meldung", "gestartet", "beendet"}`; `status` „laeuft“ | „fertig“ | „fehler“, `fortschritt` 0–100 oder
  `null` (Installer und Start: unbekannt), `meldung` letzte Ausgabezeile bzw. Ergebnis oder Fehler;
  404 „Auftrag nicht gefunden“ (unbekannt oder länger als 10 Minuten beendet).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from ...schutz import schreibschutz
from . import einrichten, erkennung

router = APIRouter(prefix="/api/ki")
_SCHUTZ = [Depends(schreibschutz)]


async def _body(request: Request) -> dict:
    """Liest den Body selbst: eine 422-Antwort von FastAPI würde die Eingabe (den Schlüssel) zurückschicken."""
    try:
        daten = await request.json()
    except ValueError:
        daten = None
    return daten if isinstance(daten, dict) else {}


async def _ausfuehren(fn, *args):
    """Blockierende Arbeit (Netz, Prozesse) im Threadpool; `einrichten.Fehler` → HTTP-Fehler."""
    try:
        return await run_in_threadpool(fn, *args)
    except einrichten.Fehler as e:
        raise HTTPException(e.status, e.meldung) from None


def _gestartet(kennung: str) -> JSONResponse:
    return JSONResponse({"auftrag": kennung}, status_code=202)


@router.get("/zustaende")
def zustaende(neu: bool = False):
    """Zustände der KIs; `neu=1` umgeht den Zwischenspeicher. Synchron: die Prüfung blockiert bis zu 5 s."""
    liste = [einrichten.mit_auftrag(z) for z in erkennung.zustaende(neu=neu)]
    return {"zustaende": liste, "keine_bereit": bool(liste) and all(z.zustand != "bereit" for z in liste)}


@router.post("/gemini/schluessel", dependencies=_SCHUTZ)
async def gemini_schluessel(request: Request):
    return await _ausfuehren(einrichten.gemini_schluessel, (await _body(request)).get("schluessel"))


@router.post("/claude/installieren", dependencies=_SCHUTZ)
async def claude_installieren():
    return _gestartet(await _ausfuehren(einrichten.claude_installieren))


@router.get("/ollama/vorschlaege")
async def ollama_vorschlaege():
    return await _ausfuehren(einrichten.ollama_vorschlaege)


@router.post("/ollama/modell", dependencies=_SCHUTZ)
async def ollama_modell(request: Request):
    ergebnis = await _ausfuehren(einrichten.ollama_modell, (await _body(request)).get("name"))
    return _gestartet(ergebnis) if isinstance(ergebnis, str) else ergebnis


@router.post("/ollama/starten", dependencies=_SCHUTZ)
async def ollama_starten():
    return _gestartet(await _ausfuehren(einrichten.ollama_starten))


@router.get("/auftraege/{kennung}")
def auftrag(kennung: str):
    if (a := einrichten.auftrag(kennung)) is None:
        raise HTTPException(404, "Auftrag nicht gefunden")
    return a
