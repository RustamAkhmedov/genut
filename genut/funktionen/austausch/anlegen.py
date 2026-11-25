"""Geprüftes Paket als neues Projekt anlegen, alles oder nichts; dazu die Herkunft (research.md R7, R8)."""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import unicodedata
from datetime import datetime
from pathlib import Path

from ...config import laden, projekte_ordner
from ...pipeline import Pipeline
from ...projekt import Projekt, atomar_schreiben
from .einlesen import Geprueft
from .schema import Herkunft

HERKUNFT = "herkunft.json"
OHNE_NAMEN = "Importiertes Projekt"
MAX_ORDNERNAME = 80  # Zeichen des Namens für den Ordner (aus „ä“ wird „ae“, Dateisysteme erlauben 255)
MAX_DATEINAME = 120

_sperre = threading.Lock()  # sonst wählen zwei gleichzeitige Importe denselben Ordner


def _dateiname(roh: str) -> str:
    """Basisname ohne Pfad und Steuerzeichen, höchstens 120 Zeichen."""
    name = (roh or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(c for c in name if not unicodedata.category(c).startswith("C")).strip()
    return name[:MAX_DATEINAME] or "unbekannt.html"


def _ordner() -> set[Path]:
    basis = projekte_ordner()
    return set(basis.iterdir()) if basis.exists() else set()


def _anlegen(g: Geprueft) -> Projekt:
    pp = g.paket.projekt
    name = pp.name.strip() or OHNE_NAMEN
    with _sperre:
        vorher = _ordner()
        try:
            p = Projekt.anlegen(name[:MAX_ORDNERNAME], fach=pp.fach, modell=laden()["modell"]["standard"],
                                einstellungen=pp.einstellungen)
        except BaseException:
            for rest in _ordner() - vorher:  # halb angelegt: noch ohne projekt.json
                if not (rest / "projekt.json").exists():
                    shutil.rmtree(rest, ignore_errors=True)
            raise
    if len(name) > MAX_ORDNERNAME:
        try:
            m = p.meta()
            m.name = name
            p.meta_speichern(m)
        except BaseException:
            shutil.rmtree(p.ordner, ignore_errors=True)
            raise
    return p


def _bild_schreiben(pfad: Path, daten: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=pfad.parent, prefix=f".{pfad.name}.")
    with os.fdopen(fd, "wb") as f:
        f.write(daten)
    os.replace(tmp, pfad)


def importieren(g: Geprueft, dateiname: str) -> dict:
    """Neues Projekt aus `g`. `RuntimeError`, wenn nichts angelegt wurde. Scheitert erst das Prüfen oder
    Bauen, bleibt das Projekt, und `warnung` sagt warum."""
    p = None
    try:
        p = _anlegen(g)
        for _, name, daten in g.bilder:
            _bild_schreiben(p.fotos / name, daten)
        p.inhalt_speichern(g.doc)
        herkunft = Herkunft(importiert_am=datetime.now().isoformat(timespec="seconds"),
                            dateiname=_dateiname(dateiname), format=g.paket.format)
        atomar_schreiben(p.ordner / HERKUNFT, herkunft.model_dump_json(indent=2))
    except BaseException as e:
        if p is not None:
            shutil.rmtree(p.ordner, ignore_errors=True)
        if not isinstance(e, Exception):
            raise
        raise RuntimeError(f"Import fehlgeschlagen, es wurde nichts angelegt: {e}") from e

    status, warnung = {}, None
    try:
        status = Pipeline(p).pruefen_bauen()["status"]
    except Exception as e:
        warnung = (f"Prüfen/Bauen fehlgeschlagen: {e} "
                   "Das Projekt wurde angelegt, bitte im Projekt neu bauen.")
    return {"slug": p.slug, "name": p.meta().name, "status": status, "warnung": warnung}


def herkunft_lesen(p: Projekt) -> Herkunft | None:
    try:
        return Herkunft.model_validate_json((p.ordner / HERKUNFT).read_text(encoding="utf-8"))
    except (OSError, ValueError):  # fehlt oder ungültig: gilt nicht als importiert
        return None


def alle_herkuenfte() -> dict[str, dict]:
    alle = ((p.slug, herkunft_lesen(p)) for p in Projekt.alle())
    return {slug: h.model_dump() for slug, h in alle if h is not None}
