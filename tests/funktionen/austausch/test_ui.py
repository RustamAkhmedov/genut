"""Projekt-Austausch im Browser: Haken beim Herunterladen, Import per Knopf und Ziehen, Herkunft, Fußzeile der
heruntergeladenen Datei, 360 px ohne Querscrollen (hell und dunkel), Schalter aus.

Echter Server mit echtem Import samt Prüfen und Bauen. GENUT_BILDER=<ordner> legt dort Screenshots ab."""
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import pytest

from genut.funktionen.austausch.anlegen import importieren
from genut.funktionen.austausch.einlesen import pruefen
from genut.funktionen.austausch.paket import importierbar
from genut.pipeline import Pipeline
from genut.projekt import Projekt

WURZEL = Path(__file__).resolve().parents[3]


def _frei() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def _server(tmp_path, projekte: Path, austausch: bool = True):
    port = _frei()
    # ohne KI-Erkennung: der Server im eigenen Prozess darf keine echte CLI und nicht Google fragen (Constitution VII)
    cfg = tmp_path / "config.toml"
    cfg.write_text(f"[funktionen]\nki_einrichtung = false\npruefung = false\n"
                   f"austausch = {'true' if austausch else 'false'}\n", encoding="utf-8")
    env = {**os.environ, "GENUT_PROJEKTE": str(projekte), "GENUT_CONFIG": str(cfg)}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "genut.server:app", "--host", "127.0.0.1",
                             "--port", str(port), "--log-level", "warning"], cwd=WURZEL, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    basis = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(basis + "/api/gruppen", timeout=1).close()
                break
            except Exception:
                if proc.poll() is not None:
                    pytest.fail("Server startet nicht")
                time.sleep(0.2)
        else:
            pytest.fail("Server startet nicht")
        yield basis
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _browser_pfad() -> str:
    shot = pytest.importorskip("tests.shot")
    pfad = shot.browser_pfad()
    if pfad is None:
        pytest.skip("kein Chrome/Chromium gefunden")
    return pfad


@contextmanager
def _seite(farbschema: str):
    pfad = _browser_pfad()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=pfad, args=["--no-sandbox"])
        pg = b.new_context(viewport={"width": 360, "height": 800}, color_scheme=farbschema,
                           accept_downloads=True).new_page()
        pg.set_default_timeout(30000)
        fehler = []
        pg.on("pageerror", lambda e: fehler.append(str(e)))
        pg.on("console", lambda m: fehler.append(m.text) if m.type == "error" else None)
        try:
            yield pg
            assert fehler == []
        finally:
            b.close()


@pytest.fixture
def gebaut(projekt_mit_inhalt):
    """Projekt aus tests/fixtures/integral mit echt geprüfter und gebauter Seite."""
    _browser_pfad()  # ohne Chrome gar nicht erst bauen
    Pipeline(projekt_mit_inhalt).pruefen_bauen()
    assert projekt_mit_inhalt.ausgabe.exists()
    return projekt_mit_inhalt


def _bild(pg, name: str, farbschema: str, ganz: bool = True):
    ordner = os.environ.get("GENUT_BILDER")
    if ordner:
        pg.screenshot(path=str(Path(ordner) / f"{name}-{farbschema}.png"), full_page=ganz)


def _kein_querscroll(pg):
    assert pg.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def _ganz_sichtbar(pg, selektor: str):
    """Knopf liegt im Fenster und sein Text ist nicht abgeschnitten."""
    el = pg.locator(selektor)
    kasten = el.bounding_box()
    assert kasten and kasten["x"] >= 0 and kasten["x"] + kasten["width"] <= pg.viewport_size["width"], kasten
    assert el.evaluate("e => e.scrollWidth <= e.clientWidth && e.scrollHeight <= e.clientHeight"), selektor


def _toast_mit(pg, text: str):
    pg.wait_for_function("t => { const e = document.querySelector('#toast'); return !e.hidden && e.textContent.includes(t); }",
                         arg=text)


def _ziehen(pg, name: str, inhalt: str, typ: str):
    """Datei auf die Projektliste ziehen: dragover und drop mit eigenem DataTransfer."""
    pg.evaluate("""([name, inhalt, typ]) => {
        const dt = new DataTransfer();
        dt.items.add(new File([inhalt], name, { type: typ }));
        const liste = document.querySelector('#app').firstElementChild;
        for (const art of ['dragover', 'drop'])
          liste.dispatchEvent(new DragEvent(art, { dataTransfer: dt, bubbles: true, cancelable: true }));
    }""", [name, inhalt, typ])


# Kontrast (WCAG) der Textfarbe gegen den Seitenhintergrund; Farben über ein Canvas in sRGB umgerechnet
KONTRAST_JS = """(el) => {
  const c = document.createElement('canvas').getContext('2d', { willReadFrequently: true });
  const rgb = (f) => { c.clearRect(0, 0, 1, 1); c.fillStyle = f; c.fillRect(0, 0, 1, 1); return c.getImageData(0, 0, 1, 1).data; };
  const hell = (f) => { const [r, g, b] = [...rgb(f)].slice(0, 3).map((v) => { v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; });
    return .2126 * r + .7152 * g + .0722 * b; };
  const [a, b] = [hell(getComputedStyle(el).color), hell(getComputedStyle(document.body).backgroundColor)];
  return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
}"""

# Nach dem Scrollen ans Ende: liegt an der Mitte jeder Textzeile des Elements wirklich das Element (nichts verdeckt es)?
UNVERDECKT_JS = """(el) => [...el.getClientRects()].every((r) => {
  const t = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2); return t && el.contains(t); })"""


def _fusszeile_pruefen(pg, datei: Path, farbschema: str):
    pg.goto(datei.as_uri())
    fuss = pg.locator("footer.genut-austausch")
    fuss.wait_for()
    assert pg.evaluate("window.innerWidth") == 360
    pg.evaluate("window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' })")
    pg.wait_for_timeout(300)
    _bild(pg, "fusszeile", farbschema, ganz=False)
    assert fuss.is_visible()
    assert "Diese Datei kann in genut als Projekt importiert werden." in fuss.inner_text()
    link = fuss.locator("a")
    assert link.get_attribute("href") == "https://github.com/RustamAkhmedov/genut"
    _kein_querscroll(pg)
    assert fuss.evaluate(UNVERDECKT_JS), "Fußzeile ist verdeckt"
    assert link.evaluate(UNVERDECKT_JS), "Link in der Fußzeile ist verdeckt"
    # Text in --muted wie auf der übrigen Lernseite (hell 4,25:1, gemeinsamer Design-Wert)
    assert fuss.evaluate(KONTRAST_JS) >= 4.2
    assert link.evaluate(KONTRAST_JS) >= 4.5


@pytest.mark.parametrize("farbschema", ["light", "dark"])
def test_teilen_und_importieren(farbschema, gebaut, projekte, tmp_path):
    slug = gebaut.slug
    with _server(tmp_path, projekte) as basis, _seite(farbschema) as pg:
        pg.goto(basis + "/ui/")
        pg.wait_for_selector(".karte.projekt")
        assert pg.evaluate("matchMedia('(prefers-color-scheme: dark)').matches") == (farbschema == "dark")
        pg.wait_for_selector(".at-import-btn")
        assert pg.inner_text(".at-import-btn") == "Projekt importieren"
        _kein_querscroll(pg)
        _ganz_sichtbar(pg, ".at-import-btn")
        _ganz_sichtbar(pg, "#neuBtn")
        assert pg.locator(".chip", has_text="importiert").count() == 0

        # Export: Haken ist gesetzt und wechselt den Link
        pg.goto(f"{basis}/ui/#/p/{slug}/export")
        haken = pg.locator(".at-export input[type=checkbox]")
        haken.wait_for()
        link = pg.locator("#dlLink")
        mit, ohne = f"/api/austausch/projekte/{slug}/download", f"/api/projekte/{slug}/download"
        assert haken.is_checked() and link.get_attribute("href") == mit
        haken.uncheck()
        assert link.get_attribute("href") == ohne
        haken.check()
        assert link.get_attribute("href") == mit
        _kein_querscroll(pg)
        _bild(pg, "export", farbschema)
        with pg.expect_download() as laden:
            link.click()
        assert laden.value.suggested_filename == f"{slug}.html"
        datei = tmp_path / f"{slug}.html"
        laden.value.save_as(datei)
        assert 'id="genutQuelle"' in datei.read_text(encoding="utf-8")

        # Import per Knopf
        pg.goto(basis + "/ui/#/")
        pg.wait_for_selector(".at-import-btn")
        with pg.expect_file_chooser() as wahl:
            pg.click(".at-import-btn")
        wahl.value.set_files(datei)
        pg.wait_for_function("h => location.hash === h", arg=f"#/p/{slug}-2")
        _toast_mit(pg, "Importiert: Test Integral")
        pg.wait_for_selector("#ifr")
        assert Projekt.laden(f"{slug}-2").ausgabe.exists()
        pg.goto(basis + "/ui/#/")
        pg.wait_for_selector(".karte.projekt .chip:text-is('importiert')")
        assert pg.locator(".karte.projekt", has=pg.locator(".chip:text-is('importiert')")).evaluate_all(
            "els => els.map(e => e.getAttribute('href'))") == [f"#/p/{slug}-2"]
        _kein_querscroll(pg)

        # Foto ziehen: Hinweis, kein Projekt
        _ziehen(pg, "foto.jpg", "kein html", "image/jpeg")
        _toast_mit(pg, "Nur .html-Dateien aus genut lassen sich importieren")
        pg.wait_for_timeout(500)
        assert len(Projekt.alle()) == 2 and pg.evaluate("location.hash") == "#/"

        # Import per Ziehen
        _ziehen(pg, datei.name, datei.read_text(encoding="utf-8"), "text/html")
        pg.wait_for_function("h => location.hash === h", arg=f"#/p/{slug}-3")
        _toast_mit(pg, "Importiert: Test Integral")
        pg.wait_for_selector("#ifr")
        assert len(Projekt.alle()) == 3

        pg.goto(basis + "/ui/#/")
        pg.wait_for_function("document.querySelectorAll('.karte.projekt .chip[title^=\"Importiert am\"]').length === 2")
        pg.wait_for_selector("#toast", state="hidden")
        _kein_querscroll(pg)
        _ganz_sichtbar(pg, ".at-import-btn")
        _ganz_sichtbar(pg, "#neuBtn")
        _bild(pg, "liste", farbschema)

        # Fotos-Tab: Hinweis nur beim importierten Projekt
        pg.goto(f"{basis}/ui/#/p/{slug}-2/fotos")
        hinweis = pg.locator(".at-hinweis")
        hinweis.wait_for()
        text = hinweis.inner_text()
        assert text.startswith("Die Original-Fotos liegen beim Absender (importiert am ")
        assert re.search(r"importiert am \d\d\.\d\d\.\d{4} aus „" + re.escape(datei.name) + "“", text)
        _kein_querscroll(pg)
        _bild(pg, "fotos", farbschema)
        pg.goto(f"{basis}/ui/#/p/{slug}/fotos")
        pg.wait_for_selector("#drop")
        pg.wait_for_load_state("networkidle")
        assert pg.locator(".at-hinweis").count() == 0

        # Die heruntergeladene Datei allein im Browser (Prinzip IV)
        _fusszeile_pruefen(pg, datei, farbschema)


def test_schalter_aus(gebaut, projekte, tmp_path):
    neu = importieren(pruefen(importierbar(gebaut).encode()), "freund.html")["slug"]
    assert (projekte / neu / "herkunft.json").is_file()
    with _server(tmp_path, projekte, austausch=False) as basis, _seite("light") as pg:
        pg.goto(basis + "/ui/")
        pg.wait_for_selector(".karte.projekt")
        pg.wait_for_load_state("networkidle")
        assert pg.locator(".at-import-btn, .at-datei").count() == 0
        assert pg.locator(".chip:text-is('importiert')").count() == 0
        pg.goto(f"{basis}/ui/#/p/{gebaut.slug}/export")
        pg.wait_for_selector("#dlLink")
        pg.wait_for_load_state("networkidle")
        assert pg.locator("[data-bereich='export-herunterladen'] input").count() == 0
        assert pg.locator("#dlLink").get_attribute("href") == f"/api/projekte/{gebaut.slug}/download"
        pg.goto(f"{basis}/ui/#/p/{neu}/fotos")
        pg.wait_for_selector("#drop")
        pg.wait_for_load_state("networkidle")
        assert pg.locator(".at-hinweis").count() == 0
