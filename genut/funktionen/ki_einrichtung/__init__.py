"""Modul KI-Einrichtung (Feature 005b). Entfernbar: Ordner löschen genügt (Constitution 3.0.0)."""
from __future__ import annotations

import contextlib
import threading

from fastapi import APIRouter

from ...config import laden
from ... import funktionen
from .. import ki_zustand_quelle
# Vor `def befehle` importieren: ein späterer Erstimport des Untermoduls würde die Funktion im Paket überschreiben.
from .befehle import eintragen as _befehle_eintragen

NAME = "ki_einrichtung"


def aktiv(cfg: dict) -> bool:
    return cfg["funktionen"].get(NAME, True) is not False


def befehle(subparsers) -> None:
    _befehle_eintragen(subparsers)


def einhaengen(app) -> None:
    from . import daten, erkennung
    from .routen import router

    daten.modelle_laden()  # eine fehlerhafte modelle.toml fällt schon beim Start auf

    def quelle(name: str) -> bool | None:
        return erkennung.bereit(name) if aktiv(laden()) else None

    @contextlib.asynccontextmanager
    async def beim_start(_app):
        # Erst beim Start der App, nie beim Import (research.md R5). Nur wenn unsere Quelle noch gilt:
        # Tests entfernen oder ersetzen sie und dürfen keine echte KI abfragen (Constitution VII).
        if funktionen._ki_quelle is quelle and aktiv(laden()):
            threading.Thread(target=erkennung.erste_pruefung, daemon=True).start()
        yield

    ki_zustand_quelle(quelle)
    app.include_router(router)
    app.include_router(APIRouter(lifespan=beim_start))
