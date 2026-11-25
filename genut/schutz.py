"""Schutz schreibender Routen, die nur die eigene Oberfläche aufrufen darf (specs/005b-ein-genut/research.md R10).

Gemeinsamer Code, damit kein Funktionsmodul dafür ein anderes importieren muss. Verwendung:
`@router.post("/…", dependencies=[Depends(schreibschutz)])`.
"""
from __future__ import annotations

from fastapi import HTTPException, Request

KOPFZEILE = "X-Genut"
_HOSTS = ("127.0.0.1", "localhost")


def schreibschutz(request: Request) -> None:
    """403, außer: `X-Genut: 1` (löst bei fremden Seiten eine CORS-Vorabfrage aus, die der Server nicht
    erlaubt), `Host` ist `127.0.0.1:<port>` oder `localhost:<port>` (gegen DNS-Rebinding) und ein
    gesendeter `Origin` nennt denselben Wert. <port> ist der Port, auf dem die Anfrage ankam."""
    server = request.scope.get("server")
    host = request.headers.get("host", "").lower()
    origin = request.headers.get("origin")
    if (request.headers.get(KOPFZEILE) != "1"
            or not server or host not in {f"{h}:{server[1]}" for h in _HOSTS}
            or (origin is not None and origin.lower() != f"http://{host}")):
        raise HTTPException(403, "Anfrage abgelehnt: Sie kommt nicht aus der gen_Ut-Oberfläche")
