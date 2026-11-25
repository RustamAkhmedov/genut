"""Modul Lernplaner (Feature 004). Entfernbar: Ordner löschen genügt (Constitution 3.0.0)."""
from __future__ import annotations

NAME = "lernplan"


def aktiv(cfg: dict) -> bool:
    return bool(cfg.get("funktionen", {}).get(NAME, True))


def einhaengen(app) -> None:
    from .routen import router
    app.include_router(router)
