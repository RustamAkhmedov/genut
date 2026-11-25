"""Datenmodell des Pakets (Datenblock `genutQuelle`) und der Herkunft (Feature 007, data-model.md)."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from ...schema import _M, BildBlock, Dokument, Einstellungen, FachFeld

FORMAT = 1


class PaketBild(_M):
    art: Literal["foto", "datei"]  # datei = aus einem Dokument gelöstes Bild (-b<n>.jpg)
    daten: str  # "" (Bild fehlte beim Absender) oder Data-URI


class PaketProjekt(_M):
    name: str = Field(max_length=200)
    fach: FachFeld
    einstellungen: Einstellungen


class Paket(_M):
    art: Literal["genut-projekt"]
    format: int
    projekt: PaketProjekt
    inhalt: Dokument
    bilder: dict[str, PaketBild]  # Schlüssel = Kennung eines Bild-Blocks


class Herkunft(_M):
    importiert_am: str
    dateiname: str = Field(max_length=120)
    format: int


def bild_bloecke(doc: Dokument) -> list[BildBlock]:
    """Alle Bild-Blöcke aus Themen und Aufgabenschritten in Dokumentreihenfolge."""
    bloecke = [b for t in doc.themen for b in t.bloecke]
    bloecke += [b for a in doc.aufgaben for s in a.schritte for b in s.bloecke]
    return [b for b in bloecke if isinstance(b, BildBlock)]
