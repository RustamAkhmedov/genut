"""Modul Mündliche Prüfung (Feature 005). Entfernbar: Ordner löschen genügt (Constitution 3.0.0)."""
from __future__ import annotations

NAME = "pruefung"


def aktiv(cfg: dict) -> bool:
    # "auto" gilt als an. Der KI-Zustand wird hier bewusst nicht abgefragt (specs/005b-ein-genut/research.md R3),
    # das tun die Routen bei jeder Anfrage.
    wert = cfg.get("funktionen", {}).get(NAME, False)
    return wert is True or wert == "auto"


def einhaengen(app) -> None:
    from .routen import router, verfuegbar_router
    app.include_router(router)
    app.include_router(verfuegbar_router)
