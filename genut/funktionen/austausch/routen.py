"""HTTP-Routen des Projekt-Austauschs (Feature 007). Der Schalter wird von der
gemeinsamen Abhängigkeit aus `genut.funktionen` je Anfrage geprüft."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from ...projekt import Projekt
from ...schutz import schreibschutz
from .anlegen import alle_herkuenfte, importieren
from .einlesen import Abgelehnt, pruefen
from .paket import importierbar

MAX_DATEI = 30 * 1024 * 1024
MAX_KOERPER = MAX_DATEI + 64 * 1024  # dazu der Multipart-Rahmen
STUECK = 1024 * 1024
ZU_GROSS = "Die Datei ist größer als 30 MB."
KEINE_DATEI = "Keine Datei übergeben."

router = APIRouter(prefix="/api/austausch")


class _ZuGross(Exception):
    pass


def _begrenzt(request: Request) -> Request:
    """Zählt die empfangenen Bytes mit: Ohne (oder mit falschem) `Content-Length` würde sonst beliebig viel
    auf die Platte gespoolt."""
    gelesen = 0

    async def receive():
        nonlocal gelesen
        nachricht = await request.receive()
        gelesen += len(nachricht.get("body", b""))
        if gelesen > MAX_KOERPER:
            raise _ZuGross
        return nachricht

    return Request(request.scope, receive)


async def _datei_lesen(request: Request) -> tuple[bytes, str]:
    """(Inhalt, Dateiname) aus dem Multipart-Feld `datei`."""
    try:
        form = await _begrenzt(request).form(max_files=1, max_fields=5)
    except _ZuGross:
        raise HTTPException(413, ZU_GROSS) from None
    except Exception:  # kaputtes Multipart oder zu viele Teile
        raise HTTPException(400, KEINE_DATEI) from None
    try:
        datei = form.get("datei")
        if not isinstance(datei, UploadFile):
            raise HTTPException(400, KEINE_DATEI)
        roh = bytearray()
        while stueck := await datei.read(STUECK):
            roh += stueck
            if len(roh) > MAX_DATEI:
                raise HTTPException(413, ZU_GROSS)
        return bytes(roh), datei.filename or ""
    finally:
        await form.close()


# Bewusst ohne UploadFile-Parameter und ohne Depends: FastAPI würde den Körper sonst schon vor Schutz und
# Größenprüfung ganz auf die Platte spoolen (research.md R4).
@router.post("/import")
async def import_(request: Request):
    schreibschutz(request)
    laenge = request.headers.get("content-length", "")
    if laenge.isdecimal() and int(laenge) > MAX_KOERPER:
        raise HTTPException(413, ZU_GROSS)
    roh, dateiname = await _datei_lesen(request)
    try:
        geprueft = await run_in_threadpool(pruefen, roh)
        return await run_in_threadpool(importieren, geprueft, dateiname)
    except Abgelehnt as e:
        raise HTTPException(400, e.meldung) from None
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from None


@router.get("/herkunft")
def herkunft():
    return {"projekte": alle_herkuenfte()}


@router.get("/projekte/{slug}/download")
def download(slug: str):
    try:
        p = Projekt.laden(slug)
    except FileNotFoundError:
        raise HTTPException(404, "Projekt nicht gefunden")
    if not p.ausgabe.exists():
        raise HTTPException(404, "Noch keine Seite gebaut")
    return Response(importierbar(p), media_type="text/html; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{p.slug}.html"'})
