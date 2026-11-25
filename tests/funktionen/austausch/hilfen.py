"""Testhilfe: gültige und beliebige (auch kaputte) Pakete bauen."""
import base64
import io
import json

from PIL import Image

from genut.bilder import ausschnitt_base64
from genut.funktionen.austausch.schema import FORMAT, bild_bloecke


def gutes_paket(p) -> dict:
    """Gültiges Paket aus der Fixture `projekt_mit_inhalt` (ein Bild-Block, Foto 001.jpg)."""
    m, doc = p.meta(), p.inhalt()
    return {
        "art": "genut-projekt",
        "format": FORMAT,
        "projekt": {"name": m.name, "fach": m.fach, "einstellungen": m.einstellungen.model_dump(mode="json")},
        "inhalt": doc.model_dump(mode="json"),
        "bilder": {b.id: {"art": "foto", "daten": ausschnitt_base64(p.fotos / b.foto, b.bbox)}
                   for b in bild_bloecke(doc)},
    }


def paket_html(obj_oder_text, *, bloecke: int = 1, typ: str = "application/json") -> bytes:
    """Minimale Seite mit `bloecke` Datenblöcken; ein Text wird unverändert (ohne JSON-Kodierung) eingesetzt."""
    text = obj_oder_text if isinstance(obj_oder_text, str) else json.dumps(obj_oder_text, ensure_ascii=False)
    block = f'<script type="{typ}" id="genutQuelle">' + text.replace("<", "\\u003c") + "</script>\n"
    return ("<!doctype html>\n<html><head><meta charset=\"utf-8\"><title>Test</title></head>\n<body>\n"
            "<p>Lernseite</p>\n" + block * bloecke + "</body></html>\n").encode("utf-8")


def bild_data_uri(format: str, breite: int, hoehe: int) -> str:
    """Data-URI eines einfarbigen Bildes (format: webp, png, jpeg …)."""
    buf = io.BytesIO()
    Image.new("RGB", (breite, hoehe), (200, 80, 40)).save(buf, format.upper())
    return f"data:image/{format.lower()};base64," + base64.b64encode(buf.getvalue()).decode()
