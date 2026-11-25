"""Importierbare Datei (research.md R3, R6 Export)."""
import json
import re
import shutil

import pytest

from genut.funktionen.austausch.paket import einbetten, importierbar, paket_bauen
from genut.funktionen.austausch.schema import Paket
from genut.pipeline import Pipeline

SEITE = "<!doctype html>\n<html><head><title>x</title></head>\n<body>\n<main>Seite</main>\n</body>\n</html>\n"
BLOCK = re.compile(r'<script type="application/json" id="genutQuelle">(.*?)</script>', re.S)


@pytest.fixture
def p(projekt_mit_inhalt):
    """Statt prerender.js laufen zu lassen, bekommt das Projekt eine kleine Seite."""
    projekt_mit_inhalt.ausgabe.write_text(SEITE, encoding="utf-8")
    return projekt_mit_inhalt


def test_paket_hat_genau_die_schluessel(p):
    paket = paket_bauen(p)
    assert set(paket) == {"art", "format", "projekt", "inhalt", "bilder"}
    assert paket["art"] == "genut-projekt" and paket["format"] == 1
    assert set(paket["projekt"]) == {"name", "fach", "einstellungen"}  # kein slug, modell, fotos, gruppe, pages
    assert paket["projekt"]["name"] == "Test Integral"
    assert paket["inhalt"] == p.inhalt().model_dump(mode="json")
    Paket.model_validate(paket)


def test_paket_bild_als_webp(p):
    (bild,) = paket_bauen(p)["bilder"].values()
    assert set(bild) == {"art", "daten"} and bild["art"] == "foto"
    assert bild["daten"].startswith("data:image/webp;base64,")


def test_paket_aus_dokument_geloestes_bild_ist_datei(p):
    doc = p.inhalt()
    block = next(b for t in doc.themen for b in t.bloecke if b.typ == "bild")
    block.foto = "001-b1.jpg"
    shutil.copy(p.fotos / "001.jpg", p.fotos / "001-b1.jpg")
    p.inhalt_speichern(doc)
    bild = paket_bauen(p)["bilder"][block.id]
    assert bild["art"] == "datei" and bild["daten"].startswith("data:image/webp;base64,")


def test_paket_fehlendes_foto_leer(p):
    (p.fotos / "001.jpg").unlink()
    assert paket_bauen(p)["bilder"]["b-00000005"] == {"art": "foto", "daten": ""}


def test_einbetten_ein_block_vor_letztem_body_rest_unveraendert():
    html = "<html><body><script>var s='</body>';</script><p>x</p></BODY></html>"
    neu = einbetten(html, {"art": "genut-projekt"})
    assert len(BLOCK.findall(neu)) == 1
    vorher, nachher = html[:html.index("</BODY>")], html[html.index("</BODY>"):]
    assert neu.startswith(vorher + "<script type=\"application/json\" id=\"genutQuelle\">") and neu.endswith(nachher)
    assert neu[len(vorher):-len(nachher)].rstrip().endswith("</footer>")


def test_einbetten_ohne_body_haengt_an():
    neu = einbetten("<p>nur ein Absatz</p>", {"a": 1})
    assert neu.startswith("<p>nur ein Absatz</p>") and len(BLOCK.findall(neu)) == 1
    assert neu.rstrip().endswith("</footer>")


def test_einbetten_kein_ausbruch_aus_dem_block():
    boese = "</script><script>alert(1)</script> <!-- <b>ä</b>"
    neu = einbetten(SEITE, {"text": boese})
    text = BLOCK.search(neu).group(1)
    assert "<" not in text and "\\u003c" in text and "ä" in text
    assert json.loads(text) == {"text": boese}
    assert neu.count("<script") == 1


def test_fusszeile_mit_link():
    neu = einbetten(SEITE, {})
    fuss = re.search(r'<footer class="genut-austausch">.*?</footer>', neu, re.S).group(0)
    assert "Diese Datei kann in genut als Projekt importiert werden." in fuss
    assert '<a href="https://github.com/RustamAkhmedov/genut">genut auf GitHub</a>' in fuss
    assert "<style>" in fuss and "var(--muted," in fuss


def test_importierbar_laesst_seite_unveraendert(p):
    roh = SEITE.replace("\n", "\r\n").encode()
    p.ausgabe.write_bytes(roh)
    neu = importierbar(p)
    assert json.loads(BLOCK.search(neu).group(1)) == paket_bauen(p)
    start = neu.index('<script type="application/json" id="genutQuelle">')
    ende = neu.index("</footer>\n") + len("</footer>\n")
    assert (neu[:start] + neu[ende:]).encode() == roh
    assert p.ausgabe.read_bytes() == roh


def test_groesse_hoechstens_doppelt(projekt_mit_inhalt):
    """SC-003, gemessen an der wirklich gebauten Seite der Fixture."""
    p = projekt_mit_inhalt
    Pipeline(p).bauen()
    assert len(importierbar(p).encode()) <= 2 * p.ausgabe.stat().st_size
