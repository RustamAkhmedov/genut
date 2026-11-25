"""Register der Projektgruppen (projekte/gruppen.json)."""
from __future__ import annotations

import json
import re
import secrets
import threading

from .config import projekte_ordner
from .projekt import Projekt, atomar_schreiben

NAME_MAX = 60
_ID_MUSTER = re.compile(r"^g-[0-9a-f]{8}$")
_sperre = threading.Lock()


class NameFehler(ValueError):
    pass


class NameVergeben(ValueError):
    pass


class GruppeUnbekannt(KeyError):
    pass


def _pfad():
    return projekte_ordner() / "gruppen.json"


def laden() -> list[dict]:
    try:
        daten = json.loads(_pfad().read_text(encoding="utf-8"))
        return [{"id": g["id"], "name": g["name"]} for g in daten["gruppen"]]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def _speichern(gruppen: list[dict]) -> None:
    atomar_schreiben(_pfad(), json.dumps({"schema_version": 1, "gruppen": gruppen}, ensure_ascii=False, indent=2))


def _name_pruefen(name: str, gruppen: list[dict], eigene_id: str | None = None) -> str:
    name = (name or "").strip()
    if not name or len(name) > NAME_MAX:
        raise NameFehler(f"Der Name muss 1 bis {NAME_MAX} Zeichen lang sein.")
    if any(g["id"] != eigene_id and g["name"].casefold() == name.casefold() for g in gruppen):
        raise NameVergeben(name)
    return name


def existiert(id: str) -> bool:
    return isinstance(id, str) and bool(_ID_MUSTER.match(id)) and any(g["id"] == id for g in laden())


def anlegen(name: str) -> dict:
    with _sperre:
        gruppen = laden()
        name = _name_pruefen(name, gruppen)
        vorhanden = {g["id"] for g in gruppen}
        while True:
            neu = f"g-{secrets.token_hex(4)}"
            if neu not in vorhanden:
                break
        gruppe = {"id": neu, "name": name}
        _speichern(gruppen + [gruppe])
        return gruppe


def umbenennen(id: str, name: str) -> dict:
    with _sperre:
        gruppen = laden()
        if not isinstance(id, str) or not _ID_MUSTER.match(id):
            raise GruppeUnbekannt(id)
        ziel = next((g for g in gruppen if g["id"] == id), None)
        if ziel is None:
            raise GruppeUnbekannt(id)
        ziel["name"] = _name_pruefen(name, gruppen, eigene_id=id)
        _speichern(gruppen)
        return dict(ziel)


def loeschen(id: str) -> int:
    with _sperre:
        gruppen = laden()
        if not isinstance(id, str) or not _ID_MUSTER.match(id) or not any(g["id"] == id for g in gruppen):
            raise GruppeUnbekannt(id)
        verschoben = 0
        for p in Projekt.alle():
            try:
                m = p.meta()
            except Exception:
                continue
            if m.gruppe == id:
                m.gruppe = None
                p.meta_speichern(m)
                verschoben += 1
        _speichern([g for g in gruppen if g["id"] != id])
        return verschoben
