"""Datenmodelle (specs/005b-ein-genut/data-model.md) und Lader für `modelle.toml`.
Keine KI-Schemas, deshalb nicht in `genut/schema.py`."""
from __future__ import annotations

import tomllib
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MODELLE_TOML = Path(__file__).with_name("modelle.toml")

KiName = Literal["claude_code", "gemini", "ollama"]


class KiZustand(BaseModel):
    name: KiName
    zustand: Literal["bereit", "nicht_eingerichtet", "problem"]
    ursache: str = ""  # leer bei „bereit“, sonst kurz, ohne Pfade und Schlüssel
    aktion: Literal["", "einrichten", "anmelden", "starten", "schluessel"] = ""
    geprueft: datetime
    auftrag: str | None = None  # Kennung eines laufenden Einrichtungsauftrags


class Rechnerprofil(BaseModel):
    ram_gb: float
    grafik: Literal["nvidia", "amd", "apple", "keine"]
    grafik_name: str = ""
    grafik_gb: float = 0
    system: Literal["linux", "macos", "windows"]
    frei_gb: float | None = None


class Modellvorschlag(BaseModel):
    name: str
    stufe: str
    download_gb: float
    bedarf_gb: float
    urteil: Literal["gut", "langsam", "zu_gross"]
    begruendung: str
    vorgewaehlt: bool = False
    platz_warnung: bool = False
    vorhanden: bool = False


class Einrichtungsauftrag(BaseModel):
    id: str = Field(pattern=r"^ke-[0-9a-f]{8}$")
    ki: KiName
    schritt: Literal["installieren", "herunterladen", "starten"]
    status: Literal["laeuft", "fertig", "fehler"]
    fortschritt: int | None = Field(default=None, ge=0, le=100)  # None = unbekannt
    meldung: str = ""  # ohne Schlüssel
    gestartet: datetime
    beendet: datetime | None = None


class Modell(BaseModel):
    """Ein Eintrag aus `modelle.toml`."""
    model_config = ConfigDict(extra="forbid")

    stufe: str = Field(min_length=1)
    name: str = Field(min_length=1)
    download_gb: float = Field(gt=0)
    bedarf_gb: float

    @model_validator(mode="after")
    def _groesse(self):
        if not self.download_gb < self.bedarf_gb:
            raise ValueError(f"{self.name}: download_gb muss kleiner als bedarf_gb sein")
        return self


class Modellliste(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modell: list[Modell] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def _liste(self):
        if len({m.name for m in self.modell}) != len(self.modell):
            raise ValueError("Modellnamen müssen eindeutig sein")
        if any(a.bedarf_gb >= b.bedarf_gb for a, b in zip(self.modell, self.modell[1:])):
            raise ValueError("Modelle müssen nach bedarf_gb aufsteigend sortiert sein")
        return self


def modelle_laden(pfad: Path = MODELLE_TOML) -> list[Modell]:
    """Liest und prüft die Modellvorschläge; wirft ValueError (auch bei kaputtem TOML)."""
    return Modellliste.model_validate(tomllib.loads(pfad.read_text(encoding="utf-8"))).modell
