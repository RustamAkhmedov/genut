"""Projekte auf der Platte: projekte/<slug>/ mit projekt.json, fotos/, transkript/, inhalt.json …"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from .config import projekte_ordner
from .schema import Dokument, ProjektKopf, ProjektMeta

VERLAUF_MAX = 20


def slug_aus(name: str) -> str:
    s = name.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "projekt"


def atomar_schreiben(pfad: Path, text: str) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=pfad.parent, prefix=f".{pfad.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, pfad)


class Projekt:
    def __init__(self, ordner: Path):
        self.ordner = ordner
        self.slug = ordner.name

    # ---------------------------------------------------------------- Pfade
    @property
    def fotos(self) -> Path:
        return self.ordner / "fotos"

    @property
    def transkripte(self) -> Path:
        return self.ordner / "transkript"

    @property
    def inhalt_pfad(self) -> Path:
        return self.ordner / "inhalt.json"

    @property
    def ausgabe(self) -> Path:
        return self.ordner / "out" / "index.html"

    @property
    def logs(self) -> Path:
        return self.ordner / "logs"

    # ---------------------------------------------------------------- Anlegen / Laden
    @classmethod
    def anlegen(cls, name: str, **meta) -> "Projekt":
        basis = projekte_ordner()
        slug = slug_aus(name)
        kandidat, n = slug, 2
        while (basis / kandidat).exists():
            kandidat, n = f"{slug}-{n}", n + 1
        ordner = basis / kandidat
        for d in ("fotos/original", "transkript", "verlauf", "logs", "out"):
            (ordner / d).mkdir(parents=True, exist_ok=True)
        p = cls(ordner)
        p.meta_speichern(ProjektMeta(name=name, slug=kandidat, **meta))
        return p

    @classmethod
    def laden(cls, slug: str) -> "Projekt":
        if not re.fullmatch(r"[a-z0-9-]+", slug):
            raise FileNotFoundError(slug)
        ordner = projekte_ordner() / slug
        if not (ordner / "projekt.json").exists():
            raise FileNotFoundError(slug)
        return cls(ordner)

    @classmethod
    def alle(cls) -> list["Projekt"]:
        basis = projekte_ordner()
        if not basis.exists():
            return []
        return [cls(d) for d in sorted(basis.iterdir()) if (d / "projekt.json").exists()]

    def meta(self) -> ProjektMeta:
        return ProjektMeta.model_validate_json((self.ordner / "projekt.json").read_text(encoding="utf-8"))

    def meta_speichern(self, m: ProjektMeta) -> None:
        atomar_schreiben(self.ordner / "projekt.json", m.model_dump_json(indent=2))

    def loeschen(self) -> None:
        papierkorb = projekte_ordner() / ".geloescht"
        papierkorb.mkdir(exist_ok=True)
        shutil.move(str(self.ordner), papierkorb / f"{self.slug}-{datetime.now():%Y%m%d-%H%M%S}")

    # ---------------------------------------------------------------- Inhalt
    def hat_inhalt(self) -> bool:
        return self.inhalt_pfad.exists()

    def inhalt(self) -> Dokument:
        if not self.inhalt_pfad.exists():
            m = self.meta()
            return Dokument(projekt=ProjektKopf(titel=m.name, fach=m.fach))
        return Dokument.model_validate_json(self.inhalt_pfad.read_text(encoding="utf-8"))

    def inhalt_speichern(self, doc: Dokument) -> None:
        if self.inhalt_pfad.exists():
            verlauf = self.ordner / "verlauf"
            verlauf.mkdir(exist_ok=True)
            shutil.copy2(self.inhalt_pfad, verlauf / f"inhalt.{datetime.now():%Y%m%d-%H%M%S-%f}.json")
            alte = sorted(verlauf.glob("inhalt.*.json"))
            for f in alte[:-VERLAUF_MAX]:
                f.unlink()
        atomar_schreiben(self.inhalt_pfad, doc.model_dump_json(indent=2))

    # ---------------------------------------------------------------- Transkripte
    def transkript_pfad(self, datei: str) -> Path:
        return self.transkripte / (Path(datei).stem + ".md")

    def transkript(self, datei: str) -> str:
        p = self.transkript_pfad(datei)
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def transkript_speichern(self, datei: str, md: str) -> None:
        atomar_schreiben(self.transkript_pfad(datei), md)

    def log(self, schritt: str, daten: dict) -> None:
        self.logs.mkdir(exist_ok=True)
        (self.logs / f"{datetime.now():%Y%m%d-%H%M%S-%f}-{schritt}.json").write_text(
            json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")
