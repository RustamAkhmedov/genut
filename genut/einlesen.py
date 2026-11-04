"""Dokumente ohne KI in Markdown-Transkripte umwandeln: md, txt, docx, pptx, pdf, html.

Bilder aus den Dokumenten werden herausgelöst und im Markdown durch Platzhalter `[[BILD n]]`
ersetzt; der Aufrufer speichert sie als Bilddatei und macht daraus eine SKIZZE-Zeile.
PDF-Seiten ohne Textebene (Scans) kommen als Bilder zurück und laufen den normalen Foto-Weg.
"""
from __future__ import annotations

import base64
import hashlib
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

DOK_ENDUNGEN = {".md", ".markdown", ".txt", ".docx", ".pptx", ".pdf", ".html", ".htm"}
MAX_BILDER = 40
MIN_BILD_PIXEL = 140 * 140       # kleinere Bilder sind fast immer Icons/Aufzählungszeichen
SCAN_MIN_ZEICHEN = 40            # PDF-Seite mit weniger Text gilt als Scan


@dataclass
class Bild:
    bild: Image.Image
    alt: str = ""


@dataclass
class Eingelesen:
    md: str = ""
    bilder: list[Bild] = field(default_factory=list)
    scanseiten: list[Image.Image] = field(default_factory=list)
    hinweise: list[str] = field(default_factory=list)


GOOGLE_HINWEIS = ("Diese Datei ist eine gespeicherte Google-Docs-Bearbeitungsansicht. Der Text steckt darin nur als Bild, "
                  "und es sind nur die Seiten dabei, die beim Speichern sichtbar waren – längere Dokumente sind unvollständig. "
                  "Die enthaltenen Seiten werden wie Fotos abgeschrieben. Besser: in Google Docs „Datei → Herunterladen → "
                  "Microsoft Word (.docx)“ wählen und die .docx hochladen.")


def _google_editor_seiten(html: str) -> list[Image.Image] | None:
    """Gespeicherter Google-Docs-Editor (Canvas-Darstellung): Text fehlt, Seiten sind als Bilder eingebettet."""
    if "kix-" not in html or ("docs.google.com" not in html and "Google Docs" not in html):
        return None
    seiten = []
    for m in re.finditer(r"data:image/(?:png|jpeg|webp);base64,([A-Za-z0-9+/=]+)", html):
        try:
            im = Image.open(io.BytesIO(base64.b64decode(m.group(1))))
            im.load()
        except Exception:  # noqa: BLE001
            continue
        if im.width >= 700 and 1.25 <= im.height / im.width <= 1.6:  # A4/Letter-Seite
            seiten.append(auf_weiss(im))
    return seiten


class EinleseFehler(ValueError):
    pass


def auf_weiss(im: Image.Image) -> Image.Image:
    """Transparente Bilder (PNG-Diagramme, Canvas-Kacheln) auf Weiß legen – sonst werden sie als JPEG schwarz."""
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        weiss = Image.new("RGB", im.size, (255, 255, 255))
        weiss.paste(im, mask=im.getchannel("A"))
        return weiss
    return im.convert("RGB")


class _Sammler:
    """Sammelt Bilder ohne Duplikate und Icons; gibt Platzhalter zurück."""

    def __init__(self):
        self.bilder: list[Bild] = []
        self._gesehen: set[str] = set()

    def add(self, daten: bytes | Image.Image, alt: str = "") -> str:
        if len(self.bilder) >= MAX_BILDER:
            return ""
        try:
            im = daten if isinstance(daten, Image.Image) else Image.open(io.BytesIO(daten))
            im.load()
        except Exception:  # noqa: BLE001 – kaputte/unbekannte Bildformate (z. B. WMF) überspringen
            return ""
        if im.width * im.height < MIN_BILD_PIXEL:
            return ""
        h = hashlib.sha1(im.tobytes()[:200000]).hexdigest()
        if h in self._gesehen:
            return ""
        self._gesehen.add(h)
        self.bilder.append(Bild(im, " ".join(alt.split())[:200]))
        return f"\n\n[[BILD {len(self.bilder)}]]\n\n"


# ---------------------------------------------------------------- Markdown aufräumen

def _aufraeumen(md: str) -> str:
    md = md.replace("\r\n", "\n").replace(" ", " ").replace("​", "")
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    md = re.sub(r"^(#{1,6})\s*\*\*(.+?)\*\*\s*$", r"\1 \2", md, flags=re.M)  # **fett** in Überschriften
    md = re.sub(r"^#{1,6}\s*$\n?", "", md, flags=re.M)                       # leere Überschriften
    # Absatz nur aus kurzem Fettdruck (ohne Satzende) = Überschrift ohne Formatvorlage
    md = re.sub(r"(?<=\n\n)\*\*([^*\n]{3,80}?)\*\*:?[ \t]*(?=\n\n|\n?$)", r"### \1", "\n\n" + md)[2:]
    return md.strip() + "\n"


# ---------------------------------------------------------------- HTML (gespeicherte Webseiten, docx über mammoth)

_WEG_TAGS = ["script", "style", "noscript", "nav", "footer", "aside", "form", "button", "iframe", "template",
             "select", "input", "svg", "canvas", "video", "audio", "object", "embed", "link", "meta"]


def _mathe_retten(soup) -> None:
    """KaTeX-, MathJax- und MathML-Formeln durch \\( … \\) bzw. \\[ … \\] ersetzen, bevor Tags entfernt werden."""
    for sel, auf, zu in (("span.katex-display", "\\[", "\\]"), ("span.katex", "\\(", "\\)")):
        for k in soup.select(sel):  # erst abgesetzte, dann übrige Inline-Formeln
            ann = k.find("annotation", attrs={"encoding": "application/x-tex"})
            if ann is not None and k.parent is not None:
                k.replace_with(f"{auf}{ann.get_text().strip()}{zu}")
    for s in soup.find_all("script", attrs={"type": re.compile(r"^math/tex")}):
        tex = s.get_text().strip()
        s.replace_with(f"\\[{tex}\\]" if "mode=display" in s.get("type", "") else f"\\({tex}\\)")
    for m in soup.find_all("math"):
        ann = m.find("annotation", attrs={"encoding": re.compile("tex", re.I)})
        if ann is not None:
            tex = ann.get_text().strip()
            m.replace_with(f"\\[{tex}\\]" if m.get("display") == "block" else f"\\({tex}\\)")
    for c in soup.find_all("mjx-container"):  # MathJax 3 ohne Quelltext: Text der Assistive-MathML
        c.replace_with(f"\\({' '.join(c.get_text().split())}\\)" if c.get_text().strip() else "")


def html_zu_md(html: str, sammler: _Sammler, extra_bilder: dict[str, tuple[bytes, str]] | None = None) -> str:
    from bs4 import BeautifulSoup
    from markdownify import markdownify

    soup = BeautifulSoup(html, "html.parser")
    titel = soup.title.get_text(" ", strip=True) if soup.title else ""
    _mathe_retten(soup)
    for t in soup(_WEG_TAGS):
        t.decompose()
    for t in soup.find_all(attrs={"aria-hidden": "true"}):
        t.decompose()
    for t in soup.find_all(attrs={"hidden": True}):
        t.decompose()
    for t in soup.find_all(style=re.compile(r"display\s*:\s*none", re.I)):
        t.decompose()
    for tab in soup.find_all("table"):  # Layout-Tabellen (1 Spalte oder 1 Zeile) in Absätze auflösen
        zeilen = tab.find_all("tr")
        spalten = max((len(z.find_all(["td", "th"])) for z in zeilen), default=0)
        if spalten <= 1 or len(zeilen) <= 1:
            ersatz = soup.new_tag("div")
            for zelle in tab.find_all(["td", "th"]):
                zelle.name = "div"
                ersatz.append(zelle.extract())
            tab.replace_with(ersatz)
    for img in soup.find_all("img"):
        src = img.get("src") or ""
        alt = img.get("alt") or img.get("title") or ""
        ersatz = ""
        if src.startswith("data:image"):
            try:
                ersatz = sammler.add(base64.b64decode(src.split(",", 1)[1]), alt)
            except (ValueError, IndexError):
                ersatz = ""
        elif extra_bilder and src in extra_bilder:
            daten, alt2 = extra_bilder[src]
            ersatz = sammler.add(daten, alt or alt2)
        elif alt.strip():
            ersatz = f" *[Bild: {alt.strip()}]* "
        img.replace_with(ersatz)
    wurzel = soup.find("main") or soup.find("article") or soup.find(attrs={"role": "main"}) or soup.body or soup
    md = markdownify(str(wurzel), heading_style="ATX", bullets="-", escape_underscores=False, escape_asterisks=False,
                     escape_misc=False, strip=["a"], code_language="", table_infer_header=True)
    md = _aufraeumen(md)
    if titel and not re.search(r"^# ", md, re.M):
        titel = re.sub(r"\s*[-–|]\s*Google (Docs|Präsentationen|Slides)$", "", titel)
        md = f"# {titel}\n\n{md}"
    return md


# ---------------------------------------------------------------- Einzelne Formate

def _text(daten: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return daten.decode(enc)
        except UnicodeDecodeError:
            continue
    return daten.decode("utf-8", errors="replace")


def _markdown(daten: bytes) -> str:
    md = _text(daten)
    md = re.sub(r"!\[([^\]]*)\]\([^)]*\)", lambda m: f"*[Bild: {m.group(1)}]*" if m.group(1) else "", md)
    md = re.sub(r"(?<!\\)\$\$(.+?)\$\$", lambda m: f"\\[{m.group(1).strip()}\\]", md, flags=re.S)
    md = re.sub(r"(?<![\\$\w])\$([^$\n]+?)\$(?!\w)", lambda m: f"\\({m.group(1).strip()}\\)", md)
    return _aufraeumen(md)


def _docx(daten: bytes, sammler: _Sammler) -> str:
    import mammoth

    bilder: dict[str, tuple[bytes, str]] = {}

    def bild(image):
        with image.open() as f:
            roh = f.read()
        key = f"genut-bild-{len(bilder)}"
        bilder[key] = (roh, image.alt_text or "")
        return {"src": key}

    try:
        erg = mammoth.convert_to_html(io.BytesIO(daten), convert_image=mammoth.images.img_element(bild))
    except Exception as e:  # noqa: BLE001
        raise EinleseFehler(f"Word-Datei nicht lesbar ({e})") from e
    hinweis = ""
    if b"<m:oMath" in _docx_xml(daten):
        hinweis = ("\n\n> [?] Diese Datei enthält Word-Formeln (Formel-Editor). Sie konnten nicht übernommen "
                   "werden – bitte im Transkript als \\( … \\) ergänzen.\n")
    return html_zu_md(erg.value, sammler, bilder) + hinweis


def _docx_xml(daten: bytes) -> bytes:
    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(daten)) as z:
            return z.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile):
        return b""


def _pptx(daten: bytes, sammler: _Sammler) -> str:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    try:
        prs = Presentation(io.BytesIO(daten))
    except Exception as e:  # noqa: BLE001
        raise EinleseFehler(f"PowerPoint-Datei nicht lesbar ({e})") from e
    teile = []

    def formen(shapes):
        for s in sorted(shapes, key=lambda s: ((s.top or 0) // 20, s.left or 0)):
            yield s

    def shape_md(s, titel_id) -> list[str]:
        out = []
        if s.shape_type == MSO_SHAPE_TYPE.GROUP:
            for x in formen(s.shapes):
                out += shape_md(x, titel_id)
            return out
        if getattr(s, "shape_id", None) == titel_id:
            return out
        if s.shape_type == MSO_SHAPE_TYPE.PICTURE or hasattr(s, "image") and getattr(s, "image", None) is not None:
            try:
                out.append(sammler.add(s.image.blob, s.name if not s.name.lower().startswith(("picture", "grafik", "bild")) else ""))
            except Exception:  # noqa: BLE001
                pass
            return out
        if getattr(s, "has_table", False) and s.has_table:
            zeilen = [[" ".join(c.text.split()) for c in r.cells] for r in s.table.rows]
            if zeilen:
                out.append("| " + " | ".join(zeilen[0]) + " |\n|" + "---|" * len(zeilen[0]) + "\n" +
                           "\n".join("| " + " | ".join(z) + " |" for z in zeilen[1:]))
            return out
        if getattr(s, "has_text_frame", False) and s.has_text_frame:
            for p in s.text_frame.paragraphs:
                t = " ".join("".join(r.text for r in p.runs).split())
                if t:
                    out.append("  " * p.level + "- " + t)
        return out

    for i, slide in enumerate(prs.slides, 1):
        titel = slide.shapes.title.text.strip() if slide.shapes.title is not None and slide.shapes.title.has_text_frame else ""
        tid = slide.shapes.title.shape_id if slide.shapes.title is not None else None
        zeilen = []
        for s in formen(slide.shapes):
            zeilen += shape_md(s, tid)
        if not titel:  # ohne Titel-Platzhalter: erste Textzeile als Titel
            erste = next((z.strip().lstrip("- ").strip() for z in zeilen if z.strip().startswith("- ")), "")
            titel = erste[:70] + ("…" if len(erste) > 70 else "")
        teile.append(f"## Folie {i}" + (f": {' '.join(titel.split())}" if titel else ""))
        teile.append("\n".join(z for z in zeilen if z.strip()))
        if slide.has_notes_slide:
            notiz = " ".join(slide.notes_slide.notes_text_frame.text.split()) if slide.notes_slide.notes_text_frame else ""
            if notiz:
                teile.append(f"> Notiz: {notiz}")
    return _aufraeumen("\n\n".join(teile))


def _pdf(daten: bytes, sammler: _Sammler) -> tuple[str, list[Image.Image]]:
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c

    try:
        pdf = pdfium.PdfDocument(daten)
    except Exception as e:  # noqa: BLE001
        raise EinleseFehler(f"PDF nicht lesbar ({e})") from e
    teile, scans = [], []
    try:
        for i in range(len(pdf)):
            seite = pdf[i]
            text = seite.get_textpage().get_text_range()
            if len(text.strip()) < SCAN_MIN_ZEICHEN:
                scans.append(seite.render(scale=2).to_pil().convert("RGB"))
                continue
            text = re.sub(r"(\w)-\r?\n(\w)", r"\1\2", text)          # Silbentrennung am Zeilenende
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            teile.append(f"## Seite {i + 1}\n\n{text.strip()}")
            for obj in seite.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE]):
                try:
                    marke = sammler.add(obj.get_bitmap(render=True).to_pil().convert("RGB"))
                except Exception:  # noqa: BLE001
                    marke = ""
                if marke:
                    teile.append(marke.strip())
    finally:
        pdf.close()
    return _aufraeumen("\n\n".join(teile)) if teile else "", scans


def einlesen(name: str, daten: bytes) -> Eingelesen:
    endung = Path(name).suffix.lower()
    if endung not in DOK_ENDUNGEN:
        raise EinleseFehler(f"Dateityp {endung or '?'} wird nicht unterstützt")
    sammler = _Sammler()
    scans: list[Image.Image] = []
    if endung in (".md", ".markdown"):
        md = _markdown(daten)
    elif endung == ".txt":
        md = _aufraeumen(_text(daten))
    elif endung == ".docx":
        md = _docx(daten, sammler)
    elif endung == ".pptx":
        md = _pptx(daten, sammler)
    elif endung == ".pdf":
        md, scans = _pdf(daten, sammler)
    else:
        html = _text(daten)
        seiten = _google_editor_seiten(html)
        if seiten is not None:
            if not seiten:
                raise EinleseFehler(GOOGLE_HINWEIS.split(" Die enthaltenen")[0] + " Es wurden keine Seiten gefunden. "
                                    "Bitte in Google Docs „Datei → Herunterladen → Microsoft Word (.docx)“ wählen.")
            return Eingelesen(scanseiten=seiten, hinweise=[GOOGLE_HINWEIS])
        md = html_zu_md(html, sammler)
    if not md.strip() and not scans:
        raise EinleseFehler(f"In {name} wurde kein Text gefunden")
    hinweise = ["Gescannte PDF-Seiten ohne Text werden wie Fotos von der KI abgeschrieben."] if scans else []
    return Eingelesen(md=md if md.strip() else "", bilder=sammler.bilder, scanseiten=scans, hinweise=hinweise)


# ---------------------------------------------------------------- Themenauswahl

_UEBERSCHRIFT = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def ueberschriften(md: str) -> list[dict]:
    """Alle Überschriften (außerhalb von Codeblöcken) mit Ebene und Textlänge des Abschnitts."""
    out, im_code = [], False
    zeilen = md.split("\n")
    for i, z in enumerate(zeilen):
        if z.strip().startswith("```"):
            im_code = not im_code
            continue
        m = None if im_code else _UEBERSCHRIFT.match(z)
        if m:
            out.append({"zeile": i, "ebene": len(m.group(1)), "text": m.group(2).strip()})
    for k, u in enumerate(out):
        ende = next((x["zeile"] for x in out[k + 1:] if x["ebene"] <= u["ebene"]), len(zeilen))
        u["zeichen"] = sum(len(z) for z in zeilen[u["zeile"] + 1:ende])
    return out


def abschnitte_filtern(md: str, ausgeschlossen: list[str]) -> str:
    """Entfernt Abschnitte, deren Überschrift abgewählt wurde – samt Unterabschnitten."""
    if not ausgeschlossen:
        return md
    weg = set(ausgeschlossen)
    zeilen = md.split("\n")
    behalten = [True] * len(zeilen)
    us = ueberschriften(md)
    for k, u in enumerate(us):
        if u["text"] in weg:
            ende = next((x["zeile"] for x in us[k + 1:] if x["ebene"] <= u["ebene"]), len(zeilen))
            for i in range(u["zeile"], ende):
                behalten[i] = False
    return "\n".join(z for z, b in zip(zeilen, behalten) if b)


__all__ = ["einlesen", "Eingelesen", "EinleseFehler", "DOK_ENDUNGEN", "ueberschriften", "abschnitte_filtern",
           "html_zu_md"]
