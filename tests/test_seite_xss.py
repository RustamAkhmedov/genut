"""Lernseite im Browser: Texte aus importierten Projekten dürfen nie als HTML in der Seite landen."""
import pytest

from genut.render.renderer import rendern
from genut.schema import Frage

# Als Entity geschrieben: Der Filter `striptags` im Template macht daraus wieder echtes HTML
BOSE = "Thema &lt;img src=x onerror=\"window.__eingeschleust=1\"&gt;"


def test_quiz_zeigt_thementitel_nur_als_text(doc, tmp_path):
    shot = pytest.importorskip("tests.shot")
    pfad = shot.browser_pfad()
    if pfad is None:
        pytest.skip("kein Chrome/Chromium gefunden")
    from playwright.sync_api import sync_playwright

    doc.themen[0].titel = BOSE
    doc.quiz = [Frage(id="q-1", thema_id=doc.themen[0].id, quelle="ki", art="wahrfalsch",
                      frage_md="Stimmt das?", wahr=True, erklaerung_md="Ja.")]
    ziel = tmp_path / "index.html"
    rendern(doc, None, "test", ziel)
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=pfad, args=["--no-sandbox"])
        pg = b.new_page()
        pg.goto(ziel.as_uri() + "#quiz")
        pg.wait_for_selector("#quizKarte .qz-top")
        pg.wait_for_timeout(500)
        assert pg.evaluate("window.__eingeschleust") is None
        assert pg.evaluate("document.querySelectorAll('#quizKarte img').length") == 0
        assert "<img" in pg.inner_text("#quizKarte .qz-top")  # als Text sichtbar
        b.close()
