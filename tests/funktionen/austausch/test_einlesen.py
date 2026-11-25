"""Import-Prüfung im Speicher (research.md R4–R7, contracts/api.md „400“)."""
import base64
import copy
import io
import json

import pytest
from PIL import Image, ImageFile

from genut.funktionen.austausch.einlesen import Abgelehnt, block_finden, pruefen
from genut.funktionen.austausch.paket import einbetten, paket_bauen
from genut.funktionen.austausch.schema import bild_bloecke

from .hilfen import bild_data_uri, gutes_paket, paket_html

BILD = "b-00000005"  # einziger Bild-Block der Fixture
UNGUELTIG = "Die Datei enthält keine gültigen Projektdaten: "


@pytest.fixture
def paket(projekt_mit_inhalt):
    return gutes_paket(projekt_mit_inhalt)


def abgelehnt(roh: bytes) -> str:
    with pytest.raises(Abgelehnt) as e:
        pruefen(roh)
    assert str(e.value) == e.value.meldung
    assert len(e.value.meldung) <= 200
    return e.value.meldung


def bild_block(kennung: str) -> dict:
    return {"typ": "bild", "id": kennung, "quelle": "foto", "foto": "001.jpg", "bbox": [0, 0, 1, 1], "alt": "x"}


def data_uri(roh: bytes, art: str = "png") -> str:
    return f"data:image/{art};base64," + base64.b64encode(roh).decode()


def bild_bytes(im: Image.Image, format: str, **kw) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format, **kw)
    return buf.getvalue()


def mit_bild(paket, daten: str, art: str = "foto") -> bytes:
    paket["bilder"][BILD] = {"art": art, "daten": daten}
    return paket_html(paket)


# ---------------------------------------------------------------- gültige Dateien

def test_gutes_paket(paket):
    g = pruefen(paket_html(paket))
    assert g.paket.projekt.name == "Test Integral"
    ((kennung, name, daten),) = g.bilder
    assert (kennung, name) == (BILD, "import-001.webp")
    with Image.open(io.BytesIO(daten)) as im:
        assert im.format == "WEBP"
    (b,) = bild_bloecke(g.doc)
    assert b.foto == "import-001.webp" and b.bbox == [0, 0, 1, 1]


def test_echte_importierbare_datei(projekt_mit_inhalt):
    """Hin und zurück im Speicher: Texte und Struktur bleiben (SC-002)."""
    p = projekt_mit_inhalt
    seite = '<!doctype html><html><head><script>var a = "<b>&amp;";</script></head><body><p>x</p></body></html>'
    doc = p.inhalt()
    doc.themen[0].bloecke[0].md = "a < b & c &amp; </script> <!-- ü   \\u003c"
    p.inhalt_speichern(doc)
    g = pruefen(einbetten(seite, paket_bauen(p)).encode("utf-8"))
    vorher, nachher = p.inhalt().model_dump(mode="json"), g.doc.model_dump(mode="json")
    for d in (vorher, nachher):
        for b in [b for t in d["themen"] for b in t["bloecke"]]:
            if b["typ"] == "bild":
                b["foto"], b["bbox"] = None, None
    assert nachher == vorher


def test_leeres_bild_wird_platzhalter(paket):
    g = pruefen(mit_bild(paket, ""))
    assert g.bilder == []
    assert bild_bloecke(g.doc)[0].foto == "fehlt-001.webp"


def test_bild_aus_dokument_wird_jpeg(paket):
    g = pruefen(mit_bild(paket, bild_data_uri("png", 30, 20), art="datei"))
    ((_, name, daten),) = g.bilder
    assert name == "import-001-b1.jpg"
    with Image.open(io.BytesIO(daten)) as im:
        assert im.format == "JPEG" and im.mode == "RGB" and im.size == (30, 20)


def test_nummern_in_dokumentreihenfolge(paket):
    paket["inhalt"]["aufgaben"][0]["schritte"][0]["bloecke"].append(bild_block("b-schritt"))
    paket["inhalt"]["themen"][1]["bloecke"].append(bild_block("b-thema2"))
    paket["bilder"]["b-schritt"] = {"art": "datei", "daten": bild_data_uri("jpeg", 8, 8)}
    paket["bilder"]["b-thema2"] = {"art": "foto", "daten": ""}
    g = pruefen(paket_html(paket))
    assert [b.foto for b in bild_bloecke(g.doc)] == ["import-001.webp", "fehlt-002.webp", "import-003-b1.jpg"]
    assert [(k, n) for k, n, _ in g.bilder] == [(BILD, "import-001.webp"), ("b-schritt", "import-003-b1.jpg")]


def test_transparenz_bleibt_bei_foto(paket):
    im = Image.new("RGBA", (10, 10), (255, 0, 0, 0))
    g = pruefen(mit_bild(paket, data_uri(bild_bytes(im, "PNG"))))
    with Image.open(io.BytesIO(g.bilder[0][2])) as neu:
        assert neu.mode == "RGBA"


@pytest.mark.parametrize("modus", ["P", "LA", "L", "I;16", "1"])
def test_bildmodi_werden_umgewandelt(paket, modus):
    im = Image.new(modus, (6, 6))
    if modus == "P":
        im.info["transparency"] = 0
    g = pruefen(mit_bild(paket, data_uri(bild_bytes(im, "PNG"))))
    assert g.bilder[0][2][:4] == b"RIFF"


def test_cmyk_jpeg(paket):
    roh = bild_bytes(Image.new("CMYK", (6, 6)), "JPEG")
    assert pruefen(mit_bild(paket, data_uri(roh, "jpeg"), art="datei")).bilder[0][2][:2] == b"\xff\xd8"


# ---------------------------------------------------------------- Block und Datei

def test_kein_block():
    assert abgelehnt(b"<!doctype html><html><body><p>Lernseite</p></body></html>") == (
        "Diese Datei enthält keine Projektdaten. Bitte den Absender, sie mit dem Haken "
        "„Zum Importieren für Freunde“ neu herunterzuladen.")


def test_zwei_bloecke(paket):
    assert abgelehnt(paket_html(paket, bloecke=2)) == "Die Datei enthält mehrere Datenblöcke und wird nicht importiert."


def test_falscher_type(paket):
    assert abgelehnt(paket_html(paket, typ="text/plain")) == UNGUELTIG + "Datenblock: type ist nicht application/json"


def test_ohne_type():
    assert abgelehnt(b'<script id="genutQuelle">{}</script>').startswith(UNGUELTIG + "Datenblock: type")


def test_kein_utf8():
    assert abgelehnt(b"<html>\xff\xfe</html>") == "Die Datei ist keine genut-Lernseite (keine lesbare HTML-Datei)."


def test_binaerdatei():
    assert abgelehnt(bild_bytes(Image.new("RGB", (4, 4)), "PNG")).startswith("Die Datei ist keine genut-Lernseite")


@pytest.mark.parametrize("html", [
    '<!-- <script type="application/json" id="genutQuelle">{}</script> -->',
    '<script>var s = \'<script type="application/json" id="genutQuelle">{}</scr\' + \'ipt>\';</script>',
    '<p id="genutQuelle">{}</p>',
])
def test_nur_echte_skript_bloecke_zaehlen(html):
    assert abgelehnt(html.encode()).startswith("Diese Datei enthält keine Projektdaten.")


def test_block_mit_grossbuchstaben_und_mehreren_attributen():
    html = '<SCRIPT data-x="1" ID="genutQuelle" TYPE="Application/JSON" id="anders">{"a": 1}</SCRIPT>'
    assert block_finden(html) == '{"a": 1}'


def test_block_mit_entities_bleibt_rohtext():
    assert block_finden('<script type="application/json" id="genutQuelle">"&amp;&lt;"</script>') == '"&amp;&lt;"'


def test_kaputtes_json(paket):
    m = abgelehnt(paket_html('{"art": "genut-projekt", "format": 1,'))
    assert m.startswith(UNGUELTIG + "JSON (Zeile 1, Spalte")


# ---------------------------------------------------------------- Format und Art

def test_neueres_format(paket):
    paket["format"] = 2
    paket["neues_feld"] = {"x": 1}  # neuere Version mit neuen Feldern: trotzdem die richtige Meldung
    neuer = "Diese Datei stammt aus einer neueren genut-Version. Bitte genut aktualisieren."
    assert abgelehnt(paket_html(paket)) == neuer


@pytest.mark.parametrize("wert", ["1", 1.0, True, 0, -1, None, [1]])
def test_format_ungueltig(paket, wert):
    paket["format"] = wert
    assert abgelehnt(paket_html(paket)) == UNGUELTIG + "format: fehlt oder ungültig"


def test_format_fehlt(paket):
    del paket["format"]
    assert abgelehnt(paket_html(paket)) == UNGUELTIG + "format: fehlt oder ungültig"


@pytest.mark.parametrize("wert", ["genut-paket", None, ["genut-projekt"]])
def test_art_falsch(paket, wert):
    paket["art"] = wert
    assert abgelehnt(paket_html(paket)) == UNGUELTIG + "art: kein genut-Projekt"


@pytest.mark.parametrize("text", ["[]", '"genut"', "1", "null"])
def test_kein_objekt(text):
    assert abgelehnt(paket_html(text)) == UNGUELTIG + "Datenblock: kein Objekt"


# ---------------------------------------------------------------- Schema

@pytest.mark.parametrize("pfad, stelle", [
    (("projekt",), "projekt.fremd"),
    (("inhalt", "themen", 0), "inhalt.themen.0.fremd"),
    (("inhalt", "themen", 0, "bloecke", 0), "inhalt.themen.0.bloecke.0.text.fremd"),
])
def test_unbekanntes_feld(paket, pfad, stelle):
    ziel = paket
    for teil in pfad:
        ziel = ziel[teil]
    ziel["fremd"] = 1
    assert abgelehnt(paket_html(paket)) == f"{UNGUELTIG}{stelle}: unbekanntes Feld"


def test_unbekanntes_fach(paket):
    paket["projekt"]["fach"] = "alchemie"
    assert abgelehnt(paket_html(paket)) == UNGUELTIG + "projekt.fach: unbekannter Wert"


def test_name_zu_lang(paket):
    paket["projekt"]["name"] = "x" * 201
    assert abgelehnt(paket_html(paket)) == UNGUELTIG + "projekt.name: zu lang (höchstens 200 Zeichen)"


def test_unbekannter_blocktyp_ohne_fremden_text(paket):
    paket["inhalt"]["themen"][0]["bloecke"][0]["typ"] = "<b>" + "x" * 500
    m = abgelehnt(paket_html(paket))
    assert m == UNGUELTIG + "inhalt.themen.0.bloecke.0: unbekannter Typ"


def test_fremde_schluessel_in_meldung_gekuerzt(paket):
    paket["projekt"]["‮" + "y" * 300] = 1
    m = abgelehnt(paket_html(paket))
    assert m.startswith(UNGUELTIG + "projekt.?yyy") and "y" * 60 not in m and "‮" not in m


@pytest.mark.parametrize("wert", [[1], {"a": 1}])
def test_fach_falscher_typ_ohne_ausnahme(paket, wert):
    paket["projekt"]["fach"] = wert  # der Validator von FachFeld würde sonst einen TypeError werfen
    assert abgelehnt(paket_html(paket)).startswith(UNGUELTIG)


# ---------------------------------------------------------------- Bilder: Zuordnung und Anzahl

def test_bild_block_ohne_bild(paket):
    del paket["bilder"][BILD]
    assert abgelehnt(paket_html(paket)) == f"Bild-Block {BILD} hat kein Bild in der Datei."


def test_bild_ohne_block(paket):
    paket["bilder"]["b-fremd"] = {"art": "foto", "daten": ""}
    assert abgelehnt(paket_html(paket)) == "Bild b-fremd gehört zu keinem Bild-Block."


def test_doppelte_bild_kennung(paket):
    paket["inhalt"]["aufgaben"][0]["schritte"][0]["bloecke"].append(bild_block(BILD))
    assert abgelehnt(paket_html(paket)) == f"{UNGUELTIG}Bild-Block {BILD}: Kennung doppelt"


def test_501_bilder(paket):
    bloecke = paket["inhalt"]["themen"][1]["bloecke"]
    for i in range(500):
        bloecke.append(bild_block(f"b-viel-{i}"))
        paket["bilder"][f"b-viel-{i}"] = {"art": "foto", "daten": ""}
    assert abgelehnt(paket_html(paket)) == "Die Datei enthält zu viele Bilder (höchstens 500)."


def test_500_bilder_erlaubt(paket):
    bloecke = paket["inhalt"]["themen"][1]["bloecke"]
    for i in range(499):
        bloecke.append(bild_block(f"b-viel-{i}"))
        paket["bilder"][f"b-viel-{i}"] = {"art": "foto", "daten": ""}
    assert len(pruefen(paket_html(paket)).bilder) == 1


# ---------------------------------------------------------------- Bilder: Inhalt

def test_gif(paket):
    m = abgelehnt(mit_bild(paket, bild_data_uri("gif", 4, 4)))
    assert m == f"Bild zu {BILD} ist ungültig: kein WebP, PNG oder JPEG"


@pytest.mark.parametrize("daten", ["kein bild", "data:text/html;base64,PGI+", "DATA:image/png;base64,AAAA",
                                   "data:image/svg+xml;base64,PHN2Zz4="])
def test_keine_data_uri(paket, daten):
    assert abgelehnt(mit_bild(paket, daten)) == f"Bild zu {BILD} ist ungültig: kein WebP, PNG oder JPEG"


def test_png_angabe_bei_webp(paket):
    daten = bild_data_uri("webp", 4, 4).replace("image/webp", "image/png")
    assert abgelehnt(mit_bild(paket, daten)) == f"Bild zu {BILD} ist ungültig: Format passt nicht zur Angabe"


@pytest.mark.parametrize("koerper", ["AAA!", "A", "AAAAA", "AA=A", "AAAA\n", ""])
def test_ungueltiges_base64(paket, koerper):
    m = abgelehnt(mit_bild(paket, "data:image/png;base64," + koerper))
    assert m == f"Bild zu {BILD} ist ungültig: ungültiges Base64"


def test_ueber_5_mb(paket):
    roh = b"\x89PNG\r\n\x1a\n" + b"\0" * (5 * 1024 * 1024)
    assert abgelehnt(mit_bild(paket, data_uri(roh))) == f"Bild zu {BILD} ist ungültig: größer als 5 MB"


def test_ueber_25_megapixel_vor_load(paket, monkeypatch):
    daten = bild_data_uri("png", 5001, 5001)

    def kein_load(self):
        raise AssertionError("load() vor der Größenprüfung")

    monkeypatch.setattr(ImageFile.ImageFile, "load", kein_load)
    assert abgelehnt(mit_bild(paket, daten)) == f"Bild zu {BILD} ist ungültig: mehr als 25 Megapixel"


def test_bild_bombe(paket):
    # 14000 × 14000 px: Pillow selbst wirft schon beim Öffnen DecompressionBombError
    roh = bild_bytes(Image.new("1", (14000, 14000)), "PNG")
    assert abgelehnt(mit_bild(paket, data_uri(roh))) == f"Bild zu {BILD} ist ungültig: mehr als 25 Megapixel"


@pytest.mark.parametrize("format", ["PNG", "JPEG", "WEBP"])
def test_abgeschnittene_bilddatei(paket, format):
    roh = bild_bytes(Image.effect_noise((64, 64), 50).convert("RGB"), format)
    art = format.lower()
    assert abgelehnt(mit_bild(paket, data_uri(roh[: len(roh) // 2], art))) == (
        f"Bild zu {BILD} ist ungültig: lässt sich nicht lesen")


def test_muell_mit_richtigem_kopf(paket):
    roh = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\xff" * 100
    assert abgelehnt(mit_bild(paket, data_uri(roh))) == f"Bild zu {BILD} ist ungültig: lässt sich nicht lesen"


@pytest.mark.parametrize("format", ["PNG", "WEBP"])
def test_animiertes_bild(paket, format):
    bilder = [Image.new("RGB", (8, 8), c) for c in ("red", "blue")]
    roh = bild_bytes(bilder[0], format, save_all=True, append_images=bilder[1:])
    m = abgelehnt(mit_bild(paket, data_uri(roh, format.lower())))
    assert m == f"Bild zu {BILD} ist ungültig: animierte Bilder sind nicht erlaubt"


def test_lange_kennung_in_bildmeldung_gekuerzt(paket):
    kennung = "b-" + "z" * 300
    paket["inhalt"]["themen"][0]["bloecke"][4]["id"] = kennung
    paket["bilder"] = {kennung: {"art": "foto", "daten": "data:image/gif;base64,AAAA"}}
    m = abgelehnt(paket_html(paket))
    assert m.startswith("Bild zu b-zzz") and "z" * 60 not in m and m.endswith("kein WebP, PNG oder JPEG")


@pytest.mark.parametrize("art, format", [("foto", "WEBP"), ("datei", "JPEG")])
def test_exif_und_angehaengte_bytes_verschwinden(paket, art, format):
    im = Image.effect_noise((40, 30), 40).convert("RGB")
    exif = Image.Exif()
    exif[0x010E] = "GEHEIM-EXIF"  # ImageDescription
    roh = bild_bytes(im, "JPEG", exif=exif.tobytes()) + b"GEHEIM-ANHANG" * 10
    assert b"GEHEIM-EXIF" in roh
    g = pruefen(mit_bild(paket, data_uri(roh, "jpeg"), art=art))
    neu = g.bilder[0][2]
    assert b"GEHEIM" not in neu and b"Exif" not in neu and b"EXIF" not in neu
    with Image.open(io.BytesIO(neu)) as x:
        assert x.format == format and not x.getexif() and x.size == (40, 30)


def test_png_textblock_verschwindet(paket):
    from PIL import PngImagePlugin

    info = PngImagePlugin.PngInfo()
    info.add_text("Kommentar", "GEHEIM-TEXT")
    roh = bild_bytes(Image.new("RGB", (8, 8)), "PNG", pnginfo=info)
    assert b"GEHEIM-TEXT" not in pruefen(mit_bild(paket, data_uri(roh))).bilder[0][2]


# ---------------------------------------------------------------- Prüfstatus und Serverfelder

def test_pruefstatus_wird_verworfen(paket):
    ok = {"status": "ok", "meldungen": [], "runden": 0, "zeit": "2026-11-24T10:00:00"}
    inhalt = paket["inhalt"]
    for b in [b for t in inhalt["themen"] for b in t["bloecke"]]:
        b["pruefung"] = ok
    for a in inhalt["aufgaben"]:
        a["pruefung"] = ok
        for s in a["schritte"]:
            for b in s["bloecke"]:
                b["pruefung"] = ok
    for k in inhalt["karten"]:
        k["pruefung"] = ok
    inhalt["quiz"].append({"quelle": "ki", "art": "wahrfalsch", "frage_md": "1 > 0", "wahr": True,
                           "erklaerung_md": "klar", "pruefung": ok})
    doc = pruefen(paket_html(paket)).doc
    elemente = [b for t in doc.themen for b in t.bloecke] + list(doc.aufgaben) + list(doc.karten) + list(doc.quiz)
    elemente += [b for a in doc.aufgaben for s in a.schritte for b in s.bloecke]
    assert len(elemente) > 20 and all(e.pruefung is None for e in elemente)


def test_pruefstatus_ausserhalb_von_inhalt_bleibt_fehler(paket):
    paket["projekt"]["pruefung"] = {"status": "ok"}
    assert abgelehnt(paket_html(paket)) == UNGUELTIG + "projekt.pruefung: unbekanntes Feld"


def test_graph_js_und_sql_ergebnis_aus_datei_verworfen(paket):
    """`ausdruck_js` käme in der Seite in `new Function` – es darf nie aus der fremden Datei stammen."""
    graph = {"x_min": 0, "x_max": 1, "funktionen": [{"ausdruck": "x", "ausdruck_js": "alert(1)"}]}
    paket["inhalt"]["themen"][1]["bloecke"] += [
        {"typ": "graph", "id": "b-g", "quelle": "ki", "graph": graph},
        {"typ": "sql", "id": "b-s", "quelle": "ki", "schema_sql": "", "abfrage": "",
         "ergebnis": {"spalten": ["<img src=x onerror=alert(1)>"], "zeilen": [], "fehler": None}},
    ]
    paket["inhalt"]["aufgaben"][0]["schritte"][0]["bloecke"].append(
        {"typ": "formel", "id": "b-f", "quelle": "ki", "tex": "x", "graph": copy.deepcopy(graph)})
    doc = pruefen(paket_html(paket)).doc
    alle = [b for t in doc.themen for b in t.bloecke] + [b for a in doc.aufgaben for s in a.schritte for b in s.bloecke]
    graphen = [b.graph for b in alle if b.typ in ("graph", "formel") and b.graph is not None]
    assert len(graphen) >= 3 and all(f.ausdruck_js is None for g in graphen for f in g.funktionen)
    assert all(b.ergebnis is None for b in alle if b.typ == "sql")


def test_fremder_bildpfad_wird_ersetzt(paket):
    paket["inhalt"]["themen"][0]["bloecke"][4]["foto"] = "../../../../etc/passwd"
    paket["inhalt"]["themen"][0]["bloecke"][4]["bbox"] = [0.5, 0.5, 0.1, 0.1]
    (b,) = bild_bloecke(pruefen(paket_html(paket)).doc)
    assert (b.foto, b.bbox) == ("import-001.webp", [0, 0, 1, 1])


# ---------------------------------------------------------------- Angriffe auf Parser und Zahlen

@pytest.mark.parametrize("tiefe", [100, 10_000, 1_000_000])
def test_tief_verschachtelt(paket, tiefe):
    paket["inhalt"]["themen"][0]["bloecke"][0]["md"] = "PLATZ"
    text = json.dumps(paket).replace('"PLATZ"', "[" * tiefe + "]" * tiefe)
    m = abgelehnt(paket_html(text))
    assert m.startswith(UNGUELTIG) and "zu tief verschachtelt" in m


def test_tief_verschachtelt_im_bild(paket):
    text = json.dumps(paket).replace('"bilder": {', '"bilder": {"x": ' + "[" * 5000 + "]" * 5000 + ", ", 1)
    assert "zu tief verschachtelt" in abgelehnt(paket_html(text))


@pytest.mark.parametrize("zahl", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999", "1" * 5000, "1." + "0" * 500])
def test_besondere_zahlen(paket, zahl):
    paket["inhalt"]["themen"][1]["bloecke"][0]["variablen"] = "PLATZ"
    text = json.dumps(paket).replace('"PLATZ"', zahl)
    assert abgelehnt(paket_html(text)).startswith(UNGUELTIG + "JSON: ")


def test_grosse_zahl_noch_erlaubt(paket):
    # IPv6-Hostanzahlen sind ehrlich groß
    paket["inhalt"]["themen"][1]["bloecke"][2]["graph"]["x_max"] = 2 ** 128
    pruefen(paket_html(paket))


@pytest.mark.parametrize("roh", ['"\\ud800"', '"a\\udfffb"'])
def test_einzelnes_surrogat(paket, roh):
    paket["inhalt"]["themen"][0]["bloecke"][0]["md"] = "PLATZ"
    text = json.dumps(paket).replace('"PLATZ"', roh)
    assert abgelehnt(paket_html(text)) == UNGUELTIG + "inhalt.themen.0.bloecke.0.md: ungültiges Zeichen"


def test_surrogat_im_schluessel(paket):
    text = json.dumps(paket).replace('"projekt": {', '"projekt": {"\\ud800x": 1,', 1)
    assert abgelehnt(paket_html(text)) == UNGUELTIG + "projekt.?x: ungültiges Zeichen"


def test_sonderzeichen_im_text_erlaubt(paket):
    paket["inhalt"]["themen"][0]["bloecke"][0]["md"] = "\x00‮😀 \U0010ffff"
    assert pruefen(paket_html(paket)).doc.themen[0].bloecke[0].md == "\x00‮😀 \U0010ffff"


def test_keine_ausnahme_bei_beliebigem_muell():
    """Grobe Stichprobe: nur Abgelehnt, nie eine andere Ausnahme."""
    proben = [b"", b"\xef\xbb\xbf", b"<script id=genutQuelle type=application/json>",
              b'<script id="genutQuelle" type="application/json"/>',
              b'<script type="application/json" id="genutQuelle">\xef\xbb\xbf{}</script>',
              b"<" * 10000, b"<!--" * 1000, b'<script type="application/json" id="genutQuelle">' + b"{" * 50]
    for roh in proben:
        with pytest.raises(Abgelehnt):
            pruefen(roh)
