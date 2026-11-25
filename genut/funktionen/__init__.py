"""Entfernbare Funktionsmodule (Constitution 3.0.0, FR-018a).

Jedes Modul ist ein Unterpaket `genut/funktionen/<name>/` mit `NAME`, `aktiv(cfg)` und `einhaengen(app)`,
optional mit `befehle(subparsers)` für Unterbefehle von `python -m genut`.
Ein gelöschtes Modul hat keine Routen und taucht nirgends auf; ein ausgeschaltetes antwortet mit 404.
Dieses Paket gehört zum gemeinsamen Code und wird nie gelöscht.
"""
from __future__ import annotations

import importlib
import pkgutil

from fastapi import Depends, HTTPException

from ..config import laden

_ki_quelle = None  # Funktion name -> bool | None, registriert von einem Modul


def ki_zustand_quelle(fn) -> None:
    """Registriert die Erkennung, die `ki_bereit` befragt. So hängt kein Modul von einem anderen ab."""
    global _ki_quelle
    _ki_quelle = fn


def ki_bereit(name: str) -> bool | None:
    """Ist die KI einsatzbereit? None = unbekannt (keine Quelle, KI unbekannt oder Erkennung gescheitert)."""
    if _ki_quelle is None:
        return None
    try:
        return _ki_quelle(name)
    except Exception:
        return None


def vorhanden() -> list[str]:
    """Namen der vorhandenen Module in fester (alphabetischer) Reihenfolge."""
    return sorted(m.name for m in pkgutil.iter_modules(__path__) if m.ispkg and not m.name.startswith("_"))


def _modul(name: str):
    try:
        return importlib.import_module(f"{__name__}.{name}")
    except Exception as e:
        raise RuntimeError(f"Funktionsmodul {name!r} lässt sich nicht laden: {e}. "
                           f"Behebe den Fehler oder lösche den Ordner genut/funktionen/{name}/.") from e


def aktive(cfg: dict) -> list[str]:
    """Namen der vorhandenen Module, die laut Konfiguration eingeschaltet sind."""
    return [n for n in vorhanden() if _modul(n).aktiv(cfg)]


def befehle_eintragen(subparsers, cfg: dict) -> None:
    """Lässt alle eingeschalteten Module ihre Unterbefehle eintragen."""
    for n in aktive(cfg):
        befehle = getattr(_modul(n), "befehle", None)
        if befehle:
            befehle(subparsers)


def _pruefung(name: str):
    def pruefen():
        if not _modul(name).aktiv(laden()):
            raise HTTPException(404, "Not Found")
    return pruefen


class _ModulApp:
    """Reicht alles an die App durch, hängt aber an jeden Router die Schalter-Prüfung des Moduls."""

    def __init__(self, app, name: str):
        self._app, self._name = app, name

    def include_router(self, router, **kw):
        kw["dependencies"] = [Depends(_pruefung(self._name)), *(kw.get("dependencies") or [])]
        return self._app.include_router(router, **kw)

    def __getattr__(self, attr):
        return getattr(self._app, attr)


def einhaengen_alle(app) -> list[str]:
    """Hängt alle vorhandenen Module ein (unabhängig vom Schalter; der wird je Anfrage geprüft)."""
    namen = vorhanden()
    module = [(n, _modul(n)) for n in namen]  # scheitert ein Import, bricht der Start vor dem Einhängen ab
    for n, m in module:
        m.einhaengen(_ModulApp(app, n))
    return namen
