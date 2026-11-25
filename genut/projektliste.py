"""Gruppierte und sortierte Projektliste (GET /api/projektliste)."""
from __future__ import annotations

import unicodedata

from . import faecher, gruppen

MODI = ("gruppen", "fach", "keine")
SORTIERUNGEN = ("name", "gebaut", "fach")


def name_schluessel(text: str) -> str:
    """Sortierschlüssel: ohne Groß-/Kleinschreibung, Umlaute und Akzente nach Grundbuchstabe, ß = ss."""
    t = unicodedata.normalize("NFKD", (text or "").casefold())
    return "".join(c for c in t if not unicodedata.combining(c))


def _nach_gebaut(projekte: list[dict]) -> list[dict]:
    mit = [p for p in projekte if p.get("letzter_build")]
    ohne = [p for p in projekte if not p.get("letzter_build")]
    mit.sort(key=lambda p: p.get("slug", ""))
    mit.sort(key=lambda p: p["letzter_build"], reverse=True)
    ohne.sort(key=lambda p: (name_schluessel(p.get("name", "")), p.get("slug", "")))
    return mit + ohne


def _fach_schluessel(p: dict) -> str | None:
    """Gültiger Fach-Schlüssel (alte Werte umgesetzt) oder None."""
    k = p.get("fach")
    k = faecher.ALTE_FAECHER.get(k, k)
    return k if k in faecher.FAECHER else None


def _nach_name(projekte: list[dict]) -> list[dict]:
    return sorted(projekte, key=lambda p: (name_schluessel(p.get("name", "")), p.get("slug", "")))


def _nach_fach(projekte: list[dict]) -> list[dict]:
    def schluessel(p: dict):
        k = _fach_schluessel(p)
        return (k is None, name_schluessel(faecher.FAECHER[k].name) if k else "",
                name_schluessel(p.get("name", "")), p.get("slug", ""))
    return sorted(projekte, key=schluessel)


_SORTIERER = {"gebaut": _nach_gebaut, "name": _nach_name, "fach": _nach_fach}


def _abschnitt(id: str, titel: str, art: str, liste: list[dict]) -> dict:
    return {"id": id, "titel": titel, "art": art, "anzahl": len(liste), "projekte": liste}


def abschnitte(projekte: list[dict], modus: str = "gruppen", sortierung: str = "gebaut") -> list[dict]:
    """`projekte` sind fertige Übersichten (wie /api/projekte)."""
    if modus not in MODI or sortierung not in SORTIERUNGEN:
        raise ValueError("Ungültiger Modus oder ungültige Sortierung")
    sortieren = _SORTIERER[sortierung]
    if modus == "keine":
        return [_abschnitt("alle", "Alle Projekte", "alle", sortieren(projekte))]
    if modus == "fach":
        je: dict[str, list[dict]] = {}
        ohne_fach: list[dict] = []
        for p in projekte:
            k = _fach_schluessel(p)
            (je.setdefault(k, []) if k else ohne_fach).append(p)
        res = [_abschnitt(k, faecher.FAECHER[k].name, "fach", sortieren(je[k]))
               for k in sorted(je, key=lambda k: (name_schluessel(faecher.FAECHER[k].name), k))]
        if ohne_fach:
            res.append(_abschnitt("ohne", "Ohne Fach", "ohne", sortieren(ohne_fach)))
        return res
    eigene = sorted(gruppen.laden(), key=lambda g: (name_schluessel(g["name"]), g["id"]))
    bekannt = {g["id"] for g in eigene}
    inhalt: dict[str, list[dict]] = {g["id"]: [] for g in eigene}
    ohne: list[dict] = []
    for p in projekte:
        g = p.get("gruppe")
        (inhalt[g] if g in bekannt else ohne).append(p)
    res = [_abschnitt(g["id"], g["name"], "gruppe", sortieren(inhalt[g["id"]])) for g in eigene]
    if ohne or not eigene:
        res.append(_abschnitt("ohne", "Ohne Gruppe", "ohne", sortieren(ohne)))
    return res
