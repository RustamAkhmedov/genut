"""Paketschema (data-model.md)."""
import copy

import pytest
from pydantic import ValidationError

from genut.funktionen.austausch.schema import Herkunft, Paket, bild_bloecke
from genut.schema import Dokument

from .hilfen import gutes_paket


@pytest.fixture
def paket(projekt_mit_inhalt):
    d = gutes_paket(projekt_mit_inhalt)
    d["inhalt"]["quiz"].append({"quelle": "ki", "art": "wahrfalsch", "frage_md": "1 > 0", "wahr": True,
                                "erklaerung_md": "klar"})  # die Fixture hat keine Quizfrage
    return d


def test_gutes_paket_gueltig(paket):
    p = Paket.model_validate(paket)
    assert [b.id for b in bild_bloecke(p.inhalt)] == list(p.bilder) == ["b-00000005"]
    assert p.bilder["b-00000005"].daten.startswith("data:image/webp;base64,")


@pytest.mark.parametrize("pfad", [
    (), ("projekt",), ("projekt", "einstellungen"), ("inhalt",), ("inhalt", "projekt"), ("inhalt", "themen", 0),
    ("inhalt", "themen", 0, "bloecke", 0), ("inhalt", "aufgaben", 0), ("inhalt", "aufgaben", 0, "schritte", 0),
    ("inhalt", "karten", 0), ("inhalt", "quiz", 0), ("bilder", "b-00000005"),
])
def test_unbekanntes_feld_ungueltig(paket, pfad):
    kopie = copy.deepcopy(paket)
    ziel = kopie
    for teil in pfad:
        ziel = ziel[teil]
    ziel["fremd"] = 1
    with pytest.raises(ValidationError, match="fremd"):
        Paket.model_validate(kopie)


@pytest.mark.parametrize("pfad", [("projekt",), ("inhalt", "projekt")])
def test_unbekanntes_fach_ungueltig(paket, pfad):
    ziel = paket
    for teil in pfad:
        ziel = ziel[teil]
    ziel["fach"] = "alchemie"
    with pytest.raises(ValidationError):
        Paket.model_validate(paket)


def test_name_und_dateiname_begrenzt(paket):
    paket["projekt"]["name"] = "x" * 200
    Paket.model_validate(paket)
    paket["projekt"]["name"] = "x" * 201
    with pytest.raises(ValidationError):
        Paket.model_validate(paket)
    with pytest.raises(ValidationError):
        Herkunft(importiert_am="2026-11-25T10:00:00", dateiname="x" * 121, format=1)


def test_bild_bloecke_auch_in_aufgabenschritten(doc):
    d = doc.model_dump(mode="json")
    bild = {"typ": "bild", "quelle": "foto", "foto": "001.jpg", "bbox": [0, 0, 1, 1], "alt": "x", "id": "b-schritt"}
    d["aufgaben"][-1]["schritte"][-1]["bloecke"].append(bild)
    assert [b.id for b in bild_bloecke(Dokument.model_validate(d))] == ["b-00000005", "b-schritt"]
