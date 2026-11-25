"""Datenmodell des Lernplans (projekte/.lernplaene/<id>.json), siehe specs/004-lernplaner/data-model.md."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Themenverweis(_M):
    projekt: str
    thema_id: str


class Erledigt(_M):
    projekt: str
    thema_id: str
    von: int
    bis: int

    @model_validator(mode="after")
    def _bereich(self):
        if not 0 <= self.von < self.bis:
            raise ValueError("0 <= von < bis erwartet")
        return self


class Zuordnung(_M):
    projekt: str
    thema_id: str
    datum: date
    urspruenglich: date | None = None
    teil: int
    teile: int
    von: int
    bis: int

    @model_validator(mode="after")
    def _pruefen(self):
        if not 1 <= self.teil <= self.teile:
            raise ValueError("1 <= teil <= teile erwartet")
        if not 0 <= self.von < self.bis:
            raise ValueError("0 <= von < bis erwartet")
        return self


class Lernplan(_M):
    schema_version: int = 1
    id: str = Field(pattern=r"^lp-[0-9a-f]{8}$")
    name: str
    start: date
    termin: date
    wochentage: list[int]
    projekte: list[str]
    ausgenommen: list[Themenverweis] = []
    zuordnung: list[Zuordnung] = []
    erledigt: list[Erledigt] = []
    wiederholung_erledigt: list[date] = []
    erstellt: datetime

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name darf nicht leer sein")
        if len(v) > 60:
            raise ValueError("name hoechstens 60 Zeichen")
        return v

    @field_validator("wochentage")
    @classmethod
    def _wochentage(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("mindestens ein Wochentag")
        if any(not 0 <= d <= 6 for d in v):
            raise ValueError("Wochentage 0 bis 6")
        if len(set(v)) != len(v):
            raise ValueError("Wochentage ohne Doppelte")
        return v

    @field_validator("projekte")
    @classmethod
    def _projekte(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("mindestens ein Projekt")
        return v

    @model_validator(mode="after")
    def _start_vor_termin(self):
        if self.start >= self.termin:
            raise ValueError("start muss vor termin liegen")
        return self
