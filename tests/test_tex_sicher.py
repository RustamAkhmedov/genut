"""Formeln aus fremden Dateien (Projekt-Austausch) dürfen weder Links noch Skripte, fremdes CSS oder eigene
IDs erzeugen (Constitution VI, ui/tex_sicher.js)."""
import re

from genut.render.renderer import rendern
from genut.schema import TextBlock

NUTZLAST = [
    r"\href{javascript:alert(1)}{a}",
    r"\mmlToken{mi}[href=\"javascript:alert(2)\"]{b}",
    r'\mmlToken{mi}[href="javascript:alert(3)"]{b}',
    r"\text{\href{javascript:alert(4)}{c}}",
    r"\require{html}\href{javascript:alert(5)}{d}",
    r"\style{background:url(https://evil.example/a)}{e}",
    r'\style{background-image:image-set("https://evil.example/s" 1x)}{e}',
    r"\bbox[border: 1px solid red; background-image: url(https://evil.example/b)]{f}",
    r'\mmlToken{mi}[style="background:url(https://evil.example/c)"]{g}',
    r"\colorbox{url(https://evil.example/d)}{h}",
    r"\color{url(https://evil.example/e)}{i}",
    r'\mmlToken{mi}[background="url(https://evil.example/f)" fontfamily="a;background:url(https://evil.example/g)"]{j}',
    r"\cssId{genutQuelle}{k}",
    r"\class{genutfremd}{l}",
]


def _seite(doc, tmp_path, formeln):
    md = "\n\n".join(rf"\({f}\)" for f in formeln)
    doc.themen[0].bloecke.insert(0, TextBlock(id="b-tex", typ="text", quelle="ki", md=md))
    ziel = tmp_path / "index.html"
    rendern(doc, None, "test", ziel)
    return ziel.read_text(encoding="utf-8")


def _attribute(html):
    """Alle Attributwerte echter Tags (sichtbarer Text und aria-label dürfen den Quelltext zeigen)."""
    for tag in re.findall(r"<[a-zA-Z][^<>]*>", re.sub(r"<(script|style)\b.*?</\1>", "", html, flags=re.S)):
        for name, wert in re.findall(r'([\w:-]+)="([^"]*)"', tag):
            if name != "aria-label":
                yield name, wert


def test_formeln_erzeugen_keine_links_und_kein_fremdes_css(doc, tmp_path):
    for name, wert in _attribute(_seite(doc, tmp_path, NUTZLAST)):
        assert "javascript:" not in wert.lower(), (name, wert)
        assert "evil.example" not in wert, (name, wert)
        assert not (name == "id" and wert == "genutQuelle"), wert
        assert not (name == "class" and "genutfremd" in wert), wert


def test_harmlose_farben_bleiben(doc, tmp_path):
    html = _seite(doc, tmp_path, [r"\color{red}{x}", r"\colorbox{#ffee00}{y}", r"\style{color: blue}{z}"])
    werte = " ".join(w for _, w in _attribute(html))
    assert "red" in werte and "#ffee00" in werte and "color: blue" in werte
