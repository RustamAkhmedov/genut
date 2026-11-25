"""KI-Schemas und Speichermodelle der mündlichen Prüfung, siehe specs/005-muendliche-pruefung/data-model.md.

Liegt hier statt in genut/schema.py, weil dort schon eine Klasse `Pruefung` (Block-Prüfung) existiert.
KI-Schemas: genut.schema.ki_schema(PruefungsPlan) usw."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema

ANTWORT_MAX = 4000


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- KI-Schemas

class PlanFrage(_M):
    thema_id: str
    frage: str = Field(min_length=1)
    erwartung: list[str] = Field(min_length=2, max_length=6)


class PruefungsPlan(_M):
    fragen: list[PlanFrage] = Field(max_length=12)


class Pruefungszug(_M):
    aktion: Literal["nachfrage", "weiter"]
    text: str | None = None
    punkte: int | None = Field(default=None, ge=0, le=2)
    anmerkung: str = ""

    @model_validator(mode="after")
    def _passt(self):
        if self.aktion == "nachfrage":
            if not (self.text or "").strip():
                raise ValueError("nachfrage verlangt text")
            if self.punkte is not None:
                raise ValueError("nachfrage erlaubt kein punkte")
        else:
            if self.punkte is None:
                raise ValueError("weiter verlangt punkte")
            if self.text is not None:
                raise ValueError("weiter erlaubt keinen text")
        return self


class Luecke(_M):
    thema_id: str
    hinweis: str


class Rueckmeldung(_M):
    nr: int = Field(ge=1)
    fehlte: str
    stoff_hinweis: str


class Pruefungsbewertung(_M):
    begruendung: str
    luecken: list[Luecke] = Field(max_length=5)
    rueckmeldungen: list[Rueckmeldung]


# ---------------------------------------------------------------- Speichermodelle

class PlanFrageGespeichert(PlanFrage):
    nr: int = Field(ge=1)


class Nachricht(_M):
    art: Literal["pruefer", "schueler"]
    nr: int = Field(ge=1)
    text: str
    typ: Literal["frage", "nachfrage"] | None = None  # nur Prüfer
    status: Literal["wartet", "bewertet"] | None = None  # nur Schüler

    @model_validator(mode="after")
    def _art(self):
        if self.art == "pruefer":
            if self.typ is None or self.status is not None:
                raise ValueError("pruefer braucht typ und kein status")
        else:
            if self.status is None or self.typ is not None:
                raise ValueError("schueler braucht status und kein typ")
            if len(self.text) > ANTWORT_MAX:
                raise ValueError(f"Antwort hoechstens {ANTWORT_MAX} Zeichen")
        return self


class PunkteEintrag(_M):
    nr: int = Field(ge=1)
    punkte: int = Field(ge=0, le=2)
    anmerkung: str = ""


class ErgebnisLuecke(Luecke):
    titel: str = ""
    link: SkipJsonSchema[str | None] = None  # wird beim Ausliefern gesetzt, nicht gespeichert


class ErgebnisRueckmeldung(Rueckmeldung):
    punkte: int = Field(ge=0, le=2)


class PruefungsErgebnis(_M):
    punkte: int = Field(ge=0)
    maximal: int = Field(ge=0)
    prozent: float
    note: int | None = Field(default=None, ge=1, le=5)
    note_name: str | None = None
    verkuerzt: bool = False
    begruendung: str = ""
    luecken: list[ErgebnisLuecke] = []
    rueckmeldungen: list[ErgebnisRueckmeldung] = []


class Pruefung(_M):
    schema_version: int = 1
    id: str = Field(pattern=r"^pr-[0-9a-f]{8}$")
    erstellt: datetime
    abgeschlossen: datetime | None = None
    status: Literal["laeuft", "abgeschlossen", "verkuerzt"] = "laeuft"
    themen: list[str] = Field(min_length=1)
    fragen_anzahl: int = Field(default=6, ge=3, le=12)
    sprache: str = "de"
    plan: SkipJsonSchema[list[PlanFrageGespeichert]] = []
    verlauf: list[Nachricht] = []
    punkte: SkipJsonSchema[list[PunkteEintrag]] = []
    ergebnis: PruefungsErgebnis | None = None

    @field_validator("punkte")
    @classmethod
    def _eindeutig(cls, v: list[PunkteEintrag]) -> list[PunkteEintrag]:
        if len({p.nr for p in v}) != len(v):
            raise ValueError("hoechstens ein Eintrag je nr")
        return v
