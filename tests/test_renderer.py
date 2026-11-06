import re

from genut.pruefer import elemente, pruefe
from genut.render.renderer import html_bauen, md, rendern
from tests.conftest import FIX


def test_md_schuetzt_tex():
    out = str(md(r"a_b und \(x_1 * y_2\) und **fett**"))
    assert r"\(x_1 * y_2\)" in out and "<strong>fett</strong>" in out


def test_md_escaped_html():
    assert "<script>" not in str(md("<script>alert(1)</script>"))


def test_html_enthaelt_alles(doc):
    pruefe(doc, set(elemente(doc)), FIX / "fotos")
    h = html_bauen(doc, FIX / "fotos", "integral")
    for i in ("v-start", "v-aufgaben", "v-karten", "v-spick", "v-thema-t-00000001"):
        assert f'id="{i}"' in h
    assert "data:image/webp;base64," in h                      # bild-Ausschnitt eingebettet
    assert 'data-graph="b-00000003"' in h                       # Graph mit geprüftem JS
    assert 'data-graph="b-00000014"' not in h                   # kaputter Graph nicht
    assert "⚠ Konnte nicht bestätigt werden" in h               # fehler-Kasten
    assert "✓ geprüft" in h and "⚠ ungeprüft" in h
    spick = h.split('id="v-spick"')[1]
    assert spick.count('class="blk ') == sum(1 for t in doc.themen for b in t.bloecke if b.spick)
    assert "<script src=" not in h and not re.search(r"<link(?![^>]*href=\"data:)", h)  # offline


def test_rendern_offline(doc, tmp_path):
    doc.karten = [k for k in doc.karten if k.id != "k-00000008"]  # absichtlich kaputtes TeX
    pruefe(doc, set(elemente(doc)), FIX / "fotos")
    ziel = tmp_path / "index.html"
    info = rendern(doc, FIX / "fotos", "integral", ziel)
    h = ziel.read_text(encoding="utf-8")
    assert info["bytes"] < 3 * 1024 * 1024
    assert "mjx-container" in h
    assert not re.search(r"\\\(", h.split("<script")[0])  # alle Inline-Formeln vorgerendert
    assert not re.search(r"https?://(?!www\.w3\.org)", h.replace("http://www.w3.org", ""))


def test_seite_im_browser(doc, tmp_path):
    """375/1280 px, hell/dunkel: kein Overflow, keine JS-Fehler, Schieberegler, Fortschritt (offline)."""
    import pytest

    shot = pytest.importorskip("tests.shot")
    if shot.browser_pfad() is None:
        pytest.skip("kein Chrome/Chromium gefunden")
    pruefe(doc, set(elemente(doc)), FIX / "fotos")
    ziel = tmp_path / "index.html"
    rendern(doc, FIX / "fotos", "integral", ziel)
    assert shot.pruefen(ziel) == []


def test_tex_sonderzeichen_nicht_doppelt_escaped():
    """Formeln mit <, > und & (Ungleichungen, Matrizen, Reaktionspfeile) dürfen nur einfach escaped sein."""
    from genut.schema import Dokument
    doc = Dokument.model_validate({"projekt": {"titel": "T", "fach": "chemie"}, "themen": [{"id": "t-1", "titel": "A", "quelle": "ki", "bloecke": [
        {"id": "b-1", "typ": "formel", "quelle": "ki", "tex": "a < b \\\\ \\begin{pmatrix} 1 & 2 \\end{pmatrix}"},
        {"id": "b-2", "typ": "reaktion", "quelle": "ki", "gleichung": "2H2 + O2 -> 2H2O"}]}]})
    h = html_bauen(doc, None, "t")
    assert "&amp;lt;" not in h and "&amp;gt;" not in h and "&amp;amp;" not in h
    assert "a &lt; b" in h and "1 &amp; 2" in h and "-&gt; 2H2O" in h
