"""HTTP-Routen der mündlichen Prüfung (specs/005-muendliche-pruefung/contracts/api.md). Der Schalter wird von
der gemeinsamen Abhängigkeit aus `genut.funktionen` je Anfrage geprüft (aus → 404). Bei `"auto"` gibt es die
Routen nur, solange Claude bereit ist (specs/005b-ein-genut/research.md R3)."""
from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException

from ...config import laden
from ...modelle.base import ModellFehler
from ...projekt import Projekt
from .. import ki_bereit
from . import logik


def _verfuegbar() -> bool:
    wert = laden().get("funktionen", {}).get("pruefung")
    return wert is True or (wert == "auto" and ki_bereit("claude_code") is True)


def _nur_wenn_verfuegbar() -> None:  # synchron: die Erkennung darf dauern, FastAPI nutzt dafür einen Thread
    if not _verfuegbar():
        raise HTTPException(404, "Not Found")


router = APIRouter(prefix="/api/projekte/{slug}/pruefungen", dependencies=[Depends(_nur_wenn_verfuegbar)])
verfuegbar_router = APIRouter(prefix="/api/pruefung")


@verfuegbar_router.get("/verfuegbar")
def verfuegbar() -> dict:
    return {"verfuegbar": _verfuegbar()}

_SLUG = re.compile(r"[a-z0-9-]+")
_ID = re.compile(r"pr-[0-9a-f]{8}")


def _projekt(slug: str) -> Projekt:
    if not _SLUG.fullmatch(slug):
        raise HTTPException(404, f"Projekt {slug} nicht gefunden")
    try:
        return Projekt.laden(slug)
    except FileNotFoundError:
        raise HTTPException(404, f"Projekt {slug} nicht gefunden")


def _kennung(id: str) -> str:
    if not _ID.fullmatch(id):
        raise HTTPException(404, "Prüfung nicht gefunden")
    return id


async def _ausfuehren(fn, *args):
    """Logik im Thread ausführen und ihre Ausnahmen auf HTTP-Statuscodes abbilden."""
    try:
        return await asyncio.to_thread(fn, *args)
    except logik.EingabeFehler as e:
        raise HTTPException(400, str(e))
    except logik.PruefungFehlt as e:
        raise HTTPException(404, str(e) or "Prüfung nicht gefunden")
    except (logik.VerarbeitungLaeuft, logik.ZustandFehler) as e:
        raise HTTPException(409, str(e))
    except ModellFehler as e:
        raise HTTPException(502, f"Der Prüfer ist ausgefallen: {e}")


def _liste(projekt: Projekt) -> dict:
    alle = logik.alle(projekt.slug)
    lp = logik.laufende(projekt.slug)
    return {"liste": [logik.zusammenfassung(p, projekt) for p in reversed(alle)],
            "laufend": lp.id if lp else None}


def _mit_zustand(projekt: Projekt, fn):
    def lauf(*args):
        return logik.zustand(fn(projekt, *args), projekt)
    return lauf


@router.get("")
async def liste(slug: str) -> dict:
    return await _ausfuehren(_liste, _projekt(slug))


@router.post("")
async def starten(slug: str, daten: dict) -> dict:
    projekt = _projekt(slug)
    themen, fragen = daten.get("themen"), daten.get("fragen", 6)
    if not isinstance(themen, list):
        raise HTTPException(400, "Wähle mindestens ein Thema.")
    return await _ausfuehren(_mit_zustand(projekt, logik.starten), themen, fragen)


def _holen(projekt: Projekt, id: str):
    pr = logik.laden(projekt.slug, id)
    if pr is None:
        raise logik.PruefungFehlt("Prüfung nicht gefunden")
    return logik.zustand(pr, projekt)


@router.get("/{id}")
async def holen(slug: str, id: str) -> dict:
    return await _ausfuehren(_holen, _projekt(slug), _kennung(id))


@router.post("/{id}/antwort")
async def antwort(slug: str, id: str, daten: dict) -> dict:
    projekt, id = _projekt(slug), _kennung(id)
    text = daten.get("text", "")
    if not isinstance(text, str):
        raise HTTPException(400, "„text“ muss ein Text sein.")
    return await _ausfuehren(_mit_zustand(projekt, logik.antworten), id, text)


@router.post("/{id}/weiter")
async def weiter(slug: str, id: str) -> dict:
    projekt, id = _projekt(slug), _kennung(id)
    return await _ausfuehren(_mit_zustand(projekt, logik.weiter), id)


@router.post("/{id}/beenden")
async def beenden(slug: str, id: str) -> dict:
    projekt, id = _projekt(slug), _kennung(id)
    return await _ausfuehren(_mit_zustand(projekt, logik.beenden), id)


@router.delete("/{id}")
async def loeschen(slug: str, id: str) -> dict:
    projekt, id = _projekt(slug), _kennung(id)
    if not await asyncio.to_thread(logik.loeschen, projekt.slug, id):
        raise HTTPException(404, "Prüfung nicht gefunden")
    return {"ok": True}
