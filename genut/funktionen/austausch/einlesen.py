"""Importierte Datei prüfen, nur im Speicher, ohne Plattenzugriff (research.md R4–R7).

Die Datei kommt von fremden Leuten (Prinzip VI): Jeder Fehler endet als `Abgelehnt` mit deutscher Meldung,
fremde Texte erscheinen darin nur gekürzt.
"""
from __future__ import annotations

import base64
import binascii
import io
import json
import math
import re
import unicodedata
import warnings
from dataclasses import dataclass
from html.parser import HTMLParser

from PIL import Image
from pydantic import ValidationError

from ...schema import Dokument, FormelBlock, GraphBlock, SqlBlock
from .schema import FORMAT, Paket, bild_bloecke

KENNUNG = "genutQuelle"
MAX_BILDER = 500
MAX_BILD_BYTES = 5 * 1024 * 1024
MAX_PIXEL = 25_000_000
MAX_TIEFE = 64        # ehrliche Pakete sind etwa 12 Ebenen tief
MAX_ZAHL = 100        # Zeichen je Zahl im JSON (ehrlich: höchstens etwa 40)
MAX_MELDUNG = 200
MAX_STUECK = 60       # Zeichen je fremdem Textstück in Meldungen

KEINE_DATEN = ("Diese Datei enthält keine Projektdaten. Bitte den Absender, sie mit dem Haken "
               "„Zum Importieren für Freunde“ neu herunterzuladen.")
NEUER = "Diese Datei stammt aus einer neueren genut-Version. Bitte genut aktualisieren."
KEIN_HTML = "Die Datei ist keine genut-Lernseite (keine lesbare HTML-Datei)."
MEHRERE = "Die Datei enthält mehrere Datenblöcke und wird nicht importiert."
UNGUELTIG = "Die Datei enthält keine gültigen Projektdaten: "
ZU_VIELE = f"Die Datei enthält zu viele Bilder (höchstens {MAX_BILDER})."

DATA_URI = re.compile(r"data:image/(webp|png|jpeg);base64,")
BASE64 = re.compile(r"[A-Za-z0-9+/]+=*")
FORMATE = {"webp": "WEBP", "png": "PNG", "jpeg": "JPEG"}

# Pydantic-Fehlerarten → deutscher Grund (Pydantic-Meldungen können fremde Werte enthalten)
GRUENDE = {
    "missing": "fehlt", "extra_forbidden": "unbekanntes Feld", "literal_error": "unbekannter Wert",
    "union_tag_invalid": "unbekannter Typ", "union_tag_not_found": "Typangabe fehlt",
    "string_type": "kein Text", "int_type": "keine ganze Zahl", "int_parsing": "keine ganze Zahl",
    "int_from_float": "keine ganze Zahl", "float_type": "keine Zahl", "float_parsing": "keine Zahl",
    "finite_number": "keine endliche Zahl", "bool_type": "kein Wahrheitswert", "bool_parsing": "kein Wahrheitswert",
    "list_type": "keine Liste", "dict_type": "kein Objekt", "model_type": "kein Objekt",
    "model_attributes_type": "kein Objekt", "greater_than_equal": "Wert zu klein", "less_than_equal": "Wert zu groß",
}


class Abgelehnt(Exception):
    """Die Datei wird nicht importiert; `meldung` ist für die Oberfläche (400)."""

    def __init__(self, meldung: str):
        super().__init__(meldung)
        self.meldung = meldung


@dataclass
class Geprueft:
    paket: Paket
    bilder: list[tuple[str, str, bytes]]  # (Block-Kennung, Dateiname, neu kodierte Bytes)
    doc: Dokument                         # mit neuen Bildnamen, ohne Prüfstatus


# ---------------------------------------------------------------- Meldungen

def _kurz(text) -> str:
    """Fremder Text für Meldungen: höchstens 60 Zeichen, ohne Steuer-, Format- und Ersatzzeichen."""
    s = str(text)[:MAX_STUECK + 1]
    s = "".join("?" if unicodedata.category(c).startswith("C") else c for c in s)
    return s if len(s) <= MAX_STUECK else s[:MAX_STUECK - 1] + "…"


def _ungueltig(stelle: str, grund: str) -> Abgelehnt:
    text = f"{UNGUELTIG}{stelle}: {grund}"
    return Abgelehnt(text if len(text) <= MAX_MELDUNG else text[:MAX_MELDUNG - 1] + "…")


def _stelle(pfad) -> str:
    return ".".join(_kurz(teil) for teil in pfad) or "Datenblock"


# ---------------------------------------------------------------- Block herauslösen

class _Sucher(HTMLParser):
    """Sammelt den Rohtext aller <script id="genutQuelle"> (Skriptinhalt ist für den Parser Rohtext)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.bloecke: list[tuple[str | None, list[str]]] = []  # (type, Textstücke)
        self._aktiv: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            return
        werte: dict[str, str | None] = {}
        for k, v in attrs:
            werte.setdefault(k, v)  # wie im Browser zählt das erste Vorkommen
        if werte.get("id") == KENNUNG:
            self._aktiv = []
            self.bloecke.append((werte.get("type"), self._aktiv))

    def handle_endtag(self, tag):
        if tag == "script":
            self._aktiv = None

    def handle_data(self, data):
        if self._aktiv is not None:
            self._aktiv.append(data)


def block_finden(html: str) -> str:
    """Text des einen Datenblocks `genutQuelle`; sonst `Abgelehnt`."""
    if KENNUNG not in html:  # schneller Weg für Seiten ohne Projektdaten
        raise Abgelehnt(KEINE_DATEN)
    sucher = _Sucher()
    try:
        sucher.feed(html)
        sucher.close()
    except Exception:  # der Parser wirft praktisch nie; dann ist es jedenfalls keine lesbare Seite
        raise Abgelehnt(KEIN_HTML) from None
    if not sucher.bloecke:
        raise Abgelehnt(KEINE_DATEN)
    if len(sucher.bloecke) > 1:
        raise Abgelehnt(MEHRERE)
    typ, teile = sucher.bloecke[0]
    if (typ or "").strip().lower() != "application/json":
        raise _ungueltig("Datenblock", "type ist nicht application/json")
    return "".join(teile)


# ---------------------------------------------------------------- JSON

class _Zahl(ValueError):
    pass


def _ganzzahl(s: str) -> int:
    if len(s) > MAX_ZAHL:
        raise _Zahl("Zahl mit zu vielen Ziffern")
    return int(s)


def _kommazahl(s: str) -> float:
    if len(s) > MAX_ZAHL:
        raise _Zahl("Zahl mit zu vielen Ziffern")
    f = float(s)
    if not math.isfinite(f):
        raise _Zahl("Zahl zu groß")
    return f


def _konstante(s: str):
    raise _Zahl(f"{s} ist keine erlaubte Zahl")


def _json(text: str):
    try:
        return json.loads(text, parse_int=_ganzzahl, parse_float=_kommazahl, parse_constant=_konstante)
    except json.JSONDecodeError as e:
        raise _ungueltig(f"JSON (Zeile {e.lineno}, Spalte {e.colno})", _kurz(e.msg)) from None
    except _Zahl as e:
        raise _ungueltig("JSON", str(e)) from None
    except RecursionError:
        raise _ungueltig("JSON", "zu tief verschachtelt") from None
    except ValueError as e:
        raise _ungueltig("JSON", _kurz(e)) from None


def _vorpruefen(obj) -> None:
    """Art und Formatversion vor dem Schema: Neuere Dateien sollen nicht als kaputt gelten (R5)."""
    if not isinstance(obj, dict):
        raise _ungueltig("Datenblock", "kein Objekt")
    if obj.get("art") != "genut-projekt":
        raise _ungueltig("art", "kein genut-Projekt")
    f = obj.get("format")
    if type(f) is not int or f < 1:  # kein bool, keine Zeichenkette, keine Kommazahl
        raise _ungueltig("format", "fehlt oder ungültig")
    if f > FORMAT:
        raise Abgelehnt(NEUER)


def _text_pruefen(s: str, pfad) -> None:
    # Einzelne Surrogate (aus \ud800 im JSON) ließen sich später nicht als UTF-8 speichern
    if not s.isascii():
        try:
            s.encode("utf-8")
        except UnicodeEncodeError:
            raise _ungueltig(_stelle(pfad), "ungültiges Zeichen") from None


def _roh_pruefen(obj: dict) -> None:
    """Ohne Rekursion: Tiefe begrenzen, Texte prüfen und in `inhalt` jeden Schlüssel `pruefung` entfernen (R7)."""
    pfad: list = []
    stapel = [(iter(obj.items()), False)]
    while stapel:
        kinder, im_inhalt = stapel[-1]
        for k, v in kinder:
            if isinstance(k, str):
                _text_pruefen(k, pfad + [k])
            if isinstance(v, str):
                _text_pruefen(v, pfad + [k])
            elif isinstance(v, (dict, list)):
                if len(stapel) >= MAX_TIEFE:
                    raise _ungueltig(_stelle(pfad[:8] + ["…"]), "zu tief verschachtelt")
                innen = im_inhalt or (len(stapel) == 1 and k == "inhalt")
                if isinstance(v, dict):
                    if innen:
                        v.pop("pruefung", None)
                    weiter = iter(v.items())
                else:
                    weiter = enumerate(v)
                pfad.append(k)
                stapel.append((weiter, innen))
                break
        else:
            stapel.pop()
            if pfad:
                pfad.pop()


def _schema(obj: dict) -> Paket:
    try:
        return Paket.model_validate(obj)
    except ValidationError as e:
        fehler = e.errors(include_url=False, include_input=False)[0]
        grund = GRUENDE.get(fehler["type"]) or _kurz(fehler["msg"])
        if fehler["type"] == "string_too_long":
            grund = f"zu lang (höchstens {fehler.get('ctx', {}).get('max_length')} Zeichen)"
        raise _ungueltig(_stelle(fehler["loc"]), grund) from None
    except Exception:  # z. B. TypeError aus einem Validator bei einer Liste statt eines Textes
        raise _ungueltig("Datenblock", "falscher Aufbau") from None


# ---------------------------------------------------------------- Bilder

def _neu_kodieren(im: Image.Image, art: str) -> bytes:
    """Nur die Pixel bleiben: keine Metadaten, keine angehängten Bytes (FR-020)."""
    alpha = im.has_transparency_data
    if art == "foto":
        bild = im.convert("RGBA" if alpha else "RGB")
    elif alpha:
        rgba = im.convert("RGBA")
        bild = Image.new("RGB", im.size, (255, 255, 255))
        bild.paste(rgba, mask=rgba.getchannel("A"))
    else:
        bild = im.convert("RGB")
    bild.info.clear()
    buf = io.BytesIO()
    if art == "foto":
        bild.save(buf, "WEBP", quality=85)
    else:
        bild.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _bild(kennung: str, art: str, daten: str) -> bytes:
    """Data-URI prüfen, vollständig dekodieren und neu kodieren (R6)."""
    def fehler(grund: str) -> Abgelehnt:
        return Abgelehnt(f"Bild zu {_kurz(kennung)} ist ungültig: {grund}")

    m = DATA_URI.match(daten)
    if not m:
        raise fehler("kein WebP, PNG oder JPEG")
    koerper = daten[m.end():]
    if len(koerper) > (MAX_BILD_BYTES // 3 + 1) * 4:  # vor dem Dekodieren
        raise fehler("größer als 5 MB")
    if not BASE64.fullmatch(koerper):
        raise fehler("ungültiges Base64")
    try:
        roh = base64.b64decode(koerper, validate=True)
    except (binascii.Error, ValueError):
        raise fehler("ungültiges Base64") from None
    if len(roh) > MAX_BILD_BYTES:
        raise fehler("größer als 5 MB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(roh), formats=list(FORMATE.values())) as im:
                if im.format != FORMATE[m.group(1)]:
                    raise fehler("Format passt nicht zur Angabe")
                breite, hoehe = im.size
                if breite * hoehe > MAX_PIXEL:  # vor load()
                    raise fehler("mehr als 25 Megapixel")
                if getattr(im, "n_frames", 1) != 1:
                    raise fehler("animierte Bilder sind nicht erlaubt")
                im.load()
                return _neu_kodieren(im, art)
    except Abgelehnt:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise fehler("mehr als 25 Megapixel") from None
    except Exception:
        raise fehler("lässt sich nicht lesen") from None


# ---------------------------------------------------------------- Gesamtprüfung

def _server_felder_leeren(doc: Dokument) -> None:
    """Felder, die sonst nur der Server berechnet: `ausdruck_js` landet in der Seite in `new Function`,
    darf also nie aus einer fremden Datei kommen. Das lokale Prüfen berechnet beides neu."""
    bloecke = [b for t in doc.themen for b in t.bloecke]
    bloecke += [b for a in doc.aufgaben for s in a.schritte for b in s.bloecke]
    for b in bloecke:
        if isinstance(b, (FormelBlock, GraphBlock)) and b.graph is not None:
            for f in b.graph.funktionen:
                f.ausdruck_js = None
        if isinstance(b, SqlBlock):
            b.ergebnis = None


def pruefen(roh: bytes) -> Geprueft:
    """Die hochgeladene Datei vollständig prüfen; Ergebnis nur im Speicher, sonst `Abgelehnt`."""
    try:
        html = roh.decode("utf-8")
    except UnicodeDecodeError:
        raise Abgelehnt(KEIN_HTML) from None
    obj = _json(block_finden(html))
    _vorpruefen(obj)
    _roh_pruefen(obj)
    paket = _schema(obj)

    doc = paket.inhalt
    bloecke = bild_bloecke(doc)
    if len(paket.bilder) > MAX_BILDER or len(bloecke) > MAX_BILDER:
        raise Abgelehnt(ZU_VIELE)
    gesehen: set[str] = set()
    for b in bloecke:
        if b.id in gesehen:
            raise _ungueltig(f"Bild-Block {_kurz(b.id)}", "Kennung doppelt")
        gesehen.add(b.id)
        if b.id not in paket.bilder:
            raise Abgelehnt(f"Bild-Block {_kurz(b.id)} hat kein Bild in der Datei.")
    for k in paket.bilder:
        if k not in gesehen:
            raise Abgelehnt(f"Bild {_kurz(k)} gehört zu keinem Bild-Block.")

    bilder: list[tuple[str, str, bytes]] = []
    for nr, b in enumerate(bloecke, 1):
        bild = paket.bilder[b.id]
        if not bild.daten:
            name = f"fehlt-{nr:03d}.webp"
        else:
            name = f"import-{nr:03d}.webp" if bild.art == "foto" else f"import-{nr:03d}-b1.jpg"
            bilder.append((b.id, name, _bild(b.id, bild.art, bild.daten)))
        b.foto = name  # Name aus der Datei wird nie als Pfad benutzt
        b.bbox = [0.0, 0.0, 1.0, 1.0]
    _server_felder_leeren(doc)
    return Geprueft(paket=paket, bilder=bilder, doc=doc)
