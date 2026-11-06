"""Dokumente einlesen (ohne KI), Themenauswahl, Dokumente im Projekt, Ergänzen."""
import base64
import io
import zipfile

import pytest
from PIL import Image

from genut.einlesen import EinleseFehler, abschnitte_filtern, einlesen, ueberschriften
from genut.pipeline import Pipeline, fotos_hinzufuegen
from genut.projekt import Projekt
from tests.test_pipeline import FakeModell


def png(w=320, h=200, farbe=(200, 60, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), farbe).save(buf, "PNG")
    return buf.getvalue()


def data_uri(b: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(b).decode()


HTML = f"""<!doctype html><html><head><title>Wellen – Skript</title><style>p{{color:red}}</style>
<script>alert(1)</script></head><body><nav>Menü Start Impressum</nav>
<main><h1>Wellen</h1><p>Die Frequenz ist <span class="katex"><span class="katex-mathml"><math><semantics><mrow></mrow>
<annotation encoding="application/x-tex">f = \\frac{{1}}{{T}}</annotation></semantics></math></span><span class="katex-html" aria-hidden="true">f=1/T</span></span>.</p>
<h2>Interferenz</h2><p>Überlagerung von Wellen.</p><img src="{data_uri(png())}" alt="Zwei Wellen">
<img src="{data_uri(png(16, 16))}" alt="icon"><img src="https://example.com/x.png" alt="Fernbild">
<table><tr><td>Nur eine Zelle als Rahmen</td></tr></table>
<table><tr><th>Größe</th><th>Einheit</th></tr><tr><td>f</td><td>Hz</td></tr></table></main>
<footer>© Schule</footer></body></html>"""


def test_html():
    e = einlesen("wellen.html", HTML.encode())
    md = e.md
    assert md.startswith("# Wellen") and "## Interferenz" in md
    assert "\\(f = \\frac{1}{T}\\)" in md and "f=1/T" not in md          # KaTeX-Quelle statt Darstellung
    assert "Menü" not in md and "alert" not in md and "© Schule" not in md
    assert len(e.bilder) == 1 and e.bilder[0].alt == "Zwei Wellen" and "[[BILD 1]]" in md   # Icon übersprungen
    assert "*[Bild: Fernbild]*" in md
    assert "Nur eine Zelle als Rahmen" in md and "|  |" not in md and "| Größe | Einheit |" in md


def test_google_docs_bearbeitungsansicht():
    html = (f'<html><head><title>Node.js - Google Docs</title></head><body><div class="kix-appview">'
            f'<a href="https://docs.google.com/x">Teilen</a><img src="{data_uri(png(1254, 1774, (255, 255, 255)))}">'
            f'<img src="{data_uri(png(1287, 123))}"></div></body></html>')
    e = einlesen("Node.js - Google Docs.html", html.encode())
    assert e.md == "" and len(e.scanseiten) == 1 and "Herunterladen" in e.hinweise[0]


def test_markdown_und_text():
    e = einlesen("notiz.md", "# Titel\n\nFläche $A = r^2 \\pi$ und $$E = mc^2$$\n\n![Skizze](bild.png)\n".encode())
    assert "\\(A = r^2 \\pi\\)" in e.md and "\\[E = mc^2\\]" in e.md and "*[Bild: Skizze]*" in e.md
    assert einlesen("a.txt", "Grüße aus Wien".encode("cp1252")).md.strip() == "Grüße aus Wien"
    with pytest.raises(EinleseFehler):
        einlesen("leer.txt", b"   ")
    with pytest.raises(EinleseFehler):
        einlesen("alt.doc", b"x")


def pptx_bytes() -> bytes:
    from pptx import Presentation
    from pptx.util import Inches
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "Projektziele"
    s.placeholders[1].text_frame.text = "Sportfest planen"
    p = s.placeholders[1].text_frame.add_paragraph()
    p.text, p.level = "Budget festlegen", 1
    s.shapes.add_picture(io.BytesIO(png(400, 300)), Inches(1), Inches(4))
    s2 = prs.slides.add_slide(prs.slide_layouts[6])  # leer, ohne Titel
    s2.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1)).text_frame.text = "Zeitplan"
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def test_pptx():
    e = einlesen("praes.pptx", pptx_bytes())
    assert "## Folie 1: Projektziele" in e.md and "- Sportfest planen" in e.md and "  - Budget festlegen" in e.md
    assert "## Folie 2: Zeitplan" in e.md and len(e.bilder) == 1


def docx_bytes() -> bytes:
    """Minimale Word-Datei (ohne Formatvorlagen): fetter Absatz, Text, Rahmen-Tabelle."""
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    doc = (f'<?xml version="1.0" encoding="UTF-8"?><w:document {w}><w:body>'
           '<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Doppelkontaktverfahren</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>Aus SO2 wird SO3.</w:t></w:r></w:p>'
           '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Merke: Katalysator V2O5</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
           '</w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


def test_docx():
    e = einlesen("chemie.docx", docx_bytes())
    assert "### Doppelkontaktverfahren" in e.md and "Aus SO2 wird SO3." in e.md
    assert "Merke: Katalysator V2O5" in e.md and "|" not in e.md
    assert [u["text"] for u in ueberschriften(e.md)] == ["Doppelkontaktverfahren"]


def pdf_mit_text() -> bytes:
    """Kleinstes gültiges PDF mit einer Textzeile (Helvetica)."""
    inhalt = b"BT /F1 14 Tf 72 720 Td (Das BIP misst die Wirtschaftsleistung eines Landes pro Jahr.) Tj ET"
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(inhalt) + inhalt + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


def test_pdf_text_und_scan():
    e = einlesen("bip.pdf", pdf_mit_text())
    assert "## Seite 1" in e.md and "Wirtschaftsleistung" in e.md and not e.scanseiten
    buf = io.BytesIO()
    Image.new("RGB", (800, 1100), "white").save(buf, "PDF")
    e = einlesen("scan.pdf", buf.getvalue())
    assert e.md == "" and len(e.scanseiten) == 1 and e.hinweise


def test_themenauswahl():
    md = "# A\ntext a\n## A1\ntext a1\n# B\ntext b\n```\n# kein Titel\n```\n## B1\nb1"
    assert [(u["ebene"], u["text"]) for u in ueberschriften(md)] == [(1, "A"), (2, "A1"), (1, "B"), (2, "B1")]
    gefiltert = abschnitte_filtern(md, ["A"])
    assert "text a" not in gefiltert and "text a1" not in gefiltert and "# B" in gefiltert and "# kein Titel" in gefiltert
    assert "b1" not in abschnitte_filtern(md, ["B1"]) and "text b" in abschnitte_filtern(md, ["B1"])
    assert abschnitte_filtern(md, []) == md


def test_dokumente_im_projekt(projekte):
    p = Projekt.anlegen("Doku Test", fach="syp")
    buf = io.BytesIO()
    Image.new("RGB", (800, 1100), "white").save(buf, "PDF")
    neu = fotos_hinzufuegen(p, [("praes.pptx", pptx_bytes()), ("scan.pdf", buf.getvalue()), ("wellen.html", HTML.encode())])
    arten = [(f.datei, f.art, f.status) for f in neu]
    assert arten == [("001.pptx", "dokument", "transkribiert"), ("002.jpg", "foto", "hochgeladen"),
                     ("003.html", "dokument", "transkribiert")]
    t = p.transkript("001.pptx")
    assert "[[SKIZZE art=bild foto=001-b01.jpg bbox=0,0,1,1" in t and (p.fotos / "001-b01.jpg").exists()
    assert (p.fotos / "original" / "001.pptx").exists() and (p.fotos / "002.jpg").exists()
    with pytest.raises(ValueError, match="nicht unterstützt"):
        fotos_hinzufuegen(p, [("alt.doc", b"x")])
    # Transkribieren lässt Dokumente aus, schreibt nur das Scan-Foto ab
    m = FakeModell(texte=["# Scan\nText"])
    assert Pipeline(p, modell=m).transkribieren() == ["002.jpg"]


def test_ergaenzen_und_themenauswahl_im_prompt(projekte):
    p = Projekt.anlegen("Ergänzen Test", fach="geographie")
    fotos_hinzufuegen(p, [("wellen.html", HTML.encode())])
    meta = p.meta()
    meta.fotos[0].status = "kontrolliert"
    meta.fotos[0].ausgeschlossen = ["Interferenz"]
    meta.einstellungen.probeaufgaben_pro_thema = meta.einstellungen.quiz_pro_thema = 0   # kein Nachfordern
    meta.einstellungen.karten = 0
    p.meta_speichern(meta)
    patch = {"projekt": {"titel": "Wellen"}, "neue_themen": [{"ref": "T1", "titel": "Wellen", "quelle": "foto",
                                                               "bloecke": [{"typ": "text", "quelle": "foto", "md": "Frequenz"}]}]}
    m = FakeModell(jsons=[patch, {"neue_themen": [{"ref": "T2", "titel": "Interferenz", "quelle": "ki",
                                                    "bloecke": [{"typ": "text", "quelle": "ki", "md": "Überlagerung"}]}]}])
    pl = Pipeline(p, modell=m)
    pl.generieren()
    assert "Überlagerung von Wellen" not in m.prompts[0] and "Die Frequenz ist" in m.prompts[0]   # abgewählt
    assert p.meta().fotos[0].status == "verarbeitet"
    pl.ergaenzen("Thema Interferenz fehlt")
    assert "Auftrag: Ergänzen" in m.prompts[1] and "Thema Interferenz fehlt" in m.prompts[1]
    assert [t.titel for t in p.inhalt().themen] == ["Wellen", "Interferenz"]
    with pytest.raises(ValueError):
        pl.ergaenzen("  ")


def test_api_dokument(projekte):
    from fastapi.testclient import TestClient

    from genut.server import app

    c = TestClient(app)
    slug = c.post("/api/projekte", json={"name": "API Doku", "fach": "syp"}).json()["slug"]
    r = c.post(f"/api/projekte/{slug}/fotos", files=[("dateien", ("praes.pptx", pptx_bytes(), "application/octet-stream"))])
    assert r.status_code == 200, r.text
    t = c.get(f"/api/projekte/{slug}/transkripte/001.pptx").json()
    assert t["art"] == "dokument" and [u["text"] for u in t["ueberschriften"]][:1] == ["Folie 1: Projektziele"]
    assert t["bilder"] == ["001-b01.jpg"]
    assert c.put(f"/api/projekte/{slug}/transkripte/001.pptx",
                 json={"md": t["md"], "kontrolliert": True, "ausgeschlossen": ["Folie 2: Zeitplan"]}).json()["status"] == "kontrolliert"
    assert c.get(f"/api/projekte/{slug}/transkripte/001.pptx").json()["ausgeschlossen"] == ["Folie 2: Zeitplan"]
    assert c.post(f"/api/projekte/{slug}/dokumente/001.pptx/neu_einlesen").json()["ok"]
    assert c.get(f"/api/projekte/{slug}/transkripte/001.pptx").json()["ausgeschlossen"] == []
    assert c.post(f"/api/projekte/{slug}/jobs", json={"art": "ergaenzen", "hinweis": ""}).status_code == 400
    p = Projekt.laden(slug)
    assert c.delete(f"/api/projekte/{slug}/fotos/001.pptx").status_code == 200
    assert not list(p.fotos.glob("001-b*.jpg")) and not (p.fotos / "original" / "001.pptx").exists()


def test_transparente_bilder_werden_weiss(projekte):
    """Transparente PNGs (Canvas-Kacheln, Diagramme) dürfen als JPEG nicht schwarz werden."""
    buf = io.BytesIO()
    im = Image.new("RGBA", (1254, 1774), (0, 0, 0, 0))
    im.paste((20, 20, 200, 255), (100, 100, 400, 140))  # blauer „Text“
    im.save(buf, "PNG")
    html = (f'<html><title>X - Google Docs</title><body class="kix-appview"><a href="https://docs.google.com/">x</a>'
            f'<img src="{data_uri(buf.getvalue())}"></body></html>')
    p = Projekt.anlegen("Transparenz", fach="wmc")
    (eintrag,) = fotos_hinzufuegen(p, [("doc.html", html.encode())])
    with Image.open(p.fotos / eintrag.datei) as fertig:
        assert fertig.getpixel((10, 10))[0] > 240 and fertig.getpixel((200, 120))[2] > 150
