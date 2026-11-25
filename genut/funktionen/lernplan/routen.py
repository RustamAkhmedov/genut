"""HTTP-Routen des Lernplaners (specs/004-lernplaner/contracts/api.md). Der Schalter wird von der
gemeinsamen Abhängigkeit aus `genut.funktionen` je Anfrage geprüft."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from . import logik

router = APIRouter(prefix="/api/lernplaene")


def _antwort(plan) -> dict:
    projekte = {s: logik._projekt_daten(s) for s in plan.projekte}
    return logik.plan_antwort(plan, projekte, logik.heute())


def _zusammenfassung(a: dict, namen: dict[str, str]) -> dict:
    return {"id": a["id"], "name": a["name"], "termin": a["termin"],
            "projekte": [namen.get(s, s) for s in a["projekte"]],
            "fortschritt": a["fortschritt"], "ueberfaellig": a["ueberfaellig"], "fertig": a["fertig"]}


@router.get("")
def liste() -> dict:
    out: dict[str, list] = {"aktuell": [], "archiv": []}
    jetzt = logik.heute()
    for plan in logik.alle():
        projekte = {s: logik._projekt_daten(s) for s in plan.projekte}
        a = logik.plan_antwort(plan, projekte, jetzt)
        namen = {s: p["name"] for s, p in projekte.items() if p}
        out["archiv" if plan.termin < jetzt else "aktuell"].append(_zusammenfassung(a, namen))
    return out


@router.post("")
def anlegen(daten: dict) -> dict:
    try:
        plan = logik.anlegen(daten)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _antwort(plan)


@router.get("/{id}")
def holen(id: str) -> dict:
    plan = logik.laden(id)
    if plan is None:
        raise HTTPException(404, "Plan nicht gefunden")
    return _antwort(plan)


@router.patch("/{id}")
def aendern(id: str, daten: dict) -> dict:
    try:
        plan = logik.aendern(id, daten)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if plan is None:
        raise HTTPException(404, "Plan nicht gefunden")
    return _antwort(plan)


@router.delete("/{id}")
def loeschen(id: str) -> dict:
    if not logik.loeschen(id):
        raise HTTPException(404, "Plan nicht gefunden")
    return {"ok": True}


@router.put("/{id}/erledigt")
def erledigt(id: str, daten: dict) -> dict:
    plan = logik.laden(id)
    if plan is None:
        raise HTTPException(404, "Plan nicht gefunden")
    wert = daten.get("erledigt")
    if not isinstance(wert, bool):
        raise HTTPException(400, "„erledigt“ muss wahr oder falsch sein.")
    ziel = {k: v for k, v in daten.items() if k != "erledigt"}
    try:
        plan = logik.erledigt_setzen(plan, ziel, wert)
    except ValueError as e:
        raise HTTPException(400, str(e))
    logik.speichern(plan)
    return _antwort(plan)


@router.post("/{id}/neu_verteilen")
def neu_verteilen(id: str) -> dict:
    plan = logik.laden(id)
    if plan is None:
        raise HTTPException(404, "Plan nicht gefunden")
    lasten = logik.lasten_der_projekte(plan.projekte, plan.ausgenommen)
    try:
        plan = logik.neu_verteilen(plan, lasten, logik.heute())
    except logik.KeinLerntag as e:
        raise HTTPException(400, str(e))
    logik.speichern(plan)
    return _antwort(plan)
