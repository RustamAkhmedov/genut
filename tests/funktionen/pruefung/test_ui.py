"""Mikrofon im Prüfungs-Chat (T012/T013): Fake-Spracherkennung per addInitScript, Server mit Fake-Prüfer.
Wird ohne Chrome/Chromium übersprungen (wie tests/test_tool_ui.py)."""
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from genut.schema import Dokument

WURZEL = Path(__file__).resolve().parents[3]
FIX = WURZEL / "tests" / "fixtures" / "integral"

# Fake-Spracherkennung: Tests steuern sie über window.__sr (letzte Instanz).
FAKE_SR = """
window.__srAnzahl = 0; window.__sr = null; window.__srStartFehler = null;
class FakeSR {
  constructor() { this.lang = ''; this.interimResults = false; window.__sr = this; window.__srAnzahl++; }
  start() { if (window.__srStartFehler) throw new Error(window.__srStartFehler); this.laeuft = true; }
  stop() { this.laeuft = false; this.onend && this.onend(); }
  __ergebnis(teile) {  // teile: [[text, final], ...]
    const results = teile.map(([t, f]) => Object.assign([{ transcript: t }], { isFinal: f }));
    this.onresult && this.onresult({ resultIndex: 0, results });
  }
  __fehler(art) { this.onerror && this.onerror({ error: art }); this.laeuft = false; this.onend && this.onend(); }
}
window.SpeechRecognition = FakeSR;
"""


def _frei() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def basis(tmp_path):
    projekte = tmp_path / "projekte"
    env = {**os.environ, "GENUT_PROJEKTE": str(projekte)}
    os.environ["GENUT_PROJEKTE"] = str(projekte)
    try:
        from genut.projekt import Projekt

        p = Projekt.anlegen("Test Integral")
        shutil.copy(FIX / "fotos" / "001.jpg", p.fotos / "001.jpg")
        p.inhalt_speichern(Dokument.model_validate_json((FIX / "inhalt.json").read_text(encoding="utf-8")))
        slug = p.slug
    finally:
        os.environ.pop("GENUT_PROJEKTE", None)
    port = _frei()
    proc = subprocess.Popen([sys.executable, "-m", "tests.funktionen.pruefung.fake_server", str(port)], cwd=WURZEL,
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(url + "/api/gruppen", timeout=1).close()
                break
            except Exception:
                if proc.poll() is not None:
                    pytest.fail("Fake-Server startet nicht")
                time.sleep(0.2)
        else:
            pytest.fail("Fake-Server startet nicht")
        yield url, slug
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture
def browser():
    shot = pytest.importorskip("tests.shot")
    pfad = shot.browser_pfad()
    if pfad is None:
        pytest.skip("kein Chrome/Chromium gefunden")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=pfad, args=["--no-sandbox"])
        yield b
        b.close()


def _chat(browser, basis, mit_api=True, ok_gemerkt=False):
    url, slug = basis
    ktx = browser.new_context(viewport={"width": 390, "height": 800})
    pg = ktx.new_page()
    fehler = []
    pg.on("pageerror", lambda e: fehler.append(str(e)))
    pg.add_init_script("delete window.webkitSpeechRecognition; delete window.SpeechRecognition;")
    if mit_api:
        pg.add_init_script(FAKE_SR)
    if ok_gemerkt:
        pg.add_init_script("try{localStorage.setItem('genut.mikrofon_ok','1')}catch(e){}")
    pg.goto(f"{url}/ui/#/p/{slug}/pruefung")
    pg.wait_for_selector("#prForm")
    pg.click("#prStart")
    pg.wait_for_selector("#prAntwort")
    return pg, fehler


def test_hinweis_nur_beim_ersten_klick_und_text_im_feld(browser, basis):
    pg, fehler = _chat(browser, basis)
    knopf = pg.locator("#prMikro")
    assert knopf.get_attribute("aria-pressed") == "false"
    knopf.click()
    pg.wait_for_selector("#dlg[open]")
    assert "Google" in pg.inner_text("#dlgForm")
    # Abbrechen: kein Start, nichts gemerkt
    pg.click('#dlgForm button[value="nein"]')
    assert pg.evaluate("window.__srAnzahl") == 0
    assert pg.evaluate("localStorage.getItem('genut.mikrofon_ok')") is None
    # Verstanden: startet
    knopf.click()
    pg.click('#dlgForm button[value="ja"]')
    pg.wait_for_function("window.__srAnzahl === 1")
    pg.wait_for_selector('#prMikro[aria-pressed="true"]')
    assert pg.evaluate("window.__sr.interimResults") is True
    assert pg.evaluate("window.__sr.lang") == "de-AT"
    pg.fill("#prAntwort", "Zuerst tippe ich.")
    pg.evaluate("window.__sr.laeuft = true")
    knopf.click()  # Stopp
    assert knopf.get_attribute("aria-pressed") == "false"
    # zweiter Gebrauch: kein Hinweis mehr
    knopf.click()
    pg.wait_for_selector('#prMikro[aria-pressed="true"]')
    assert pg.evaluate("window.__srAnzahl") == 2
    assert not pg.evaluate("document.querySelector('#dlg').open")
    pg.evaluate("window.__sr.__ergebnis([['Das Integral ist', true], ['eine Fläche', false]])")
    assert pg.input_value("#prAntwort") == "Zuerst tippe ich. Das Integral ist eine Fläche"
    pg.evaluate("window.__sr.__ergebnis([['Das Integral ist eine Fläche.', true]])")
    pg.evaluate("window.__sr.stop()")
    assert pg.input_value("#prAntwort") == "Zuerst tippe ich. Das Integral ist eine Fläche."
    assert knopf.get_attribute("aria-pressed") == "false"
    # nie automatisch gesendet
    assert pg.locator(".pr-zeile.schueler").count() == 0
    assert pg.evaluate("localStorage.getItem('genut.mikrofon_ok')") == "1"
    assert fehler == []


def test_ohne_spracherkennung_kein_knopf(browser, basis):
    pg, fehler = _chat(browser, basis, mit_api=False)
    assert pg.locator("#prMikro").count() == 0
    pg.fill("#prAntwort", "Tippen geht.")
    assert pg.input_value("#prAntwort") == "Tippen geht."
    assert pg.locator("#prSenden").is_enabled()
    assert fehler == []


@pytest.mark.parametrize("art, text", [("not-allowed", "Mikrofon"), ("no-speech", "nichts gehört"),
                                       ("network", "Internet")])
def test_fehler_zeigt_meldung_und_chat_bleibt_nutzbar(browser, basis, art, text):
    pg, fehler = _chat(browser, basis, ok_gemerkt=True)
    pg.click("#prMikro")
    # erst wenn die Aufnahme läuft, hängen die Handler (davor wird noch die Sprache geladen)
    pg.wait_for_selector('#prMikro[aria-pressed="true"]')
    pg.evaluate(f"window.__sr.__fehler('{art}')")
    assert text in pg.inner_text("#prMikroStatus")
    assert pg.locator("#prMikro").get_attribute("aria-pressed") == "false"
    pg.fill("#prAntwort", "Ich tippe stattdessen eine längere Antwort zum Integral als Fläche unter der Kurve.")
    assert pg.locator("#prSenden").is_enabled()
    pg.click("#prSenden")
    pg.wait_for_selector(".pr-zeile.schueler")
    assert fehler == []


# ---------------- Verlauf (T015) ----------------
ANTWORT = "Das Integral misst die Fläche unter der Kurve und ist die Umkehrung der Ableitung, grob gesagt."


def _fertig(pg):
    pg.click("#prBeenden")
    pg.click('#dlgForm button[value="ja"]')
    pg.wait_for_selector("#prNochmal")


def test_liste_loeschen_nochmal_und_fortsetzen(browser, basis):
    url, slug = basis
    pg = browser.new_context(viewport={"width": 360, "height": 800}).new_page()
    fehler = []
    pg.on("pageerror", lambda e: fehler.append(str(e)))
    pg.goto(f"{url}/ui/#/p/{slug}/pruefung")
    pg.wait_for_selector("#prForm")
    assert pg.locator(".pr-eintrag").count() == 0
    pg.click("#prStart")
    pg.wait_for_selector("#prAntwort")
    _fertig(pg)
    # Nochmal: startet sofort eine neue Prüfung mit denselben Themen
    pg.click("#prNochmal")
    pg.wait_for_selector("#prAntwort")
    # Neuladen: laufende Prüfung wird fortgesetzt
    pg.reload()
    pg.wait_for_selector("#prAntwort")
    assert pg.locator("#prForm").count() == 0
    _fertig(pg)
    pg.click("#prListe")
    pg.wait_for_selector(".pr-eintrag")
    assert pg.locator(".pr-eintrag").count() == 2
    assert "vorzeitig beendet" in pg.locator(".pr-eintrag").first.inner_text() or "Note" in pg.locator(".pr-eintrag").first.inner_text()
    assert pg.evaluate("document.documentElement.scrollWidth <= innerWidth")
    # Öffnen zeigt das Ergebnis
    pg.locator(".pr-oeffnen").first.click()
    pg.wait_for_selector("#prNochmal")
    pg.click("#prListe")
    pg.wait_for_selector(".pr-eintrag")
    # Löschen mit Rückfrage
    pg.locator(".pr-loeschen").first.click()
    pg.wait_for_selector("#dlg[open]")
    pg.click('#dlgForm button[value="nein"]')
    assert pg.locator(".pr-eintrag").count() == 2
    pg.locator(".pr-loeschen").first.click()
    pg.click('#dlgForm button[value="ja"]')
    pg.wait_for_function("document.querySelectorAll('.pr-eintrag').length === 1")
    assert fehler == []


# ---------------- Layout, Tastatur, hell/dunkel, Schalter (T016) ----------------
LANG = "Das bestimmte Integral ist der Grenzwert der Riemann-Summen und entspricht der orientierten Fläche."

KONTRAST_JS = """
(sel) => {
  const rgb = (s) => { const m = s.match(/rgba?\\(([^)]+)\\)/); if (!m) return null;
    const t = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return { r: t[0], g: t[1], b: t[2], a: t.length > 3 ? t[3] : 1 }; };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const el = document.querySelector(sel); if (!el) return null;
  const fg = rgb(getComputedStyle(el).color);
  let bg = null;
  for (let e = el; e && !bg; e = e.parentElement) { const c = rgb(getComputedStyle(e).backgroundColor); if (c && c.a > 0.99) bg = c; }
  if (!fg || !bg) return -1;
  const [a, b] = [lum(fg), lum(bg)].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05);
}
"""


def _seite(browser, basis, breite=360, schema="light"):
    url, slug = basis
    pg = browser.new_context(viewport={"width": breite, "height": 800}, color_scheme=schema).new_page()
    fehler = []
    pg.on("pageerror", lambda e: fehler.append(str(e)))
    pg.goto(f"{url}/ui/#/p/{slug}/pruefung")
    pg.wait_for_selector("#prForm")
    return pg, fehler


def _kein_querscrollen(pg):
    assert pg.evaluate("document.documentElement.scrollWidth <= innerWidth")


def _bis_ergebnis(pg, fragen=3):
    pg.fill("#prFragen", str(fragen))
    pg.click("#prStart")
    for _ in range(fragen):
        pg.wait_for_selector("#prAntwort")
        n = pg.locator(".pr-zeile.schueler").count()
        pg.fill("#prAntwort", LANG)
        pg.keyboard.press("Control+Enter")
        pg.wait_for_function(
            f"document.querySelector('#prNochmal') || (document.querySelectorAll('.pr-zeile.schueler').length > {n}"
            " && document.querySelector('#prDenkt') && document.querySelector('#prDenkt').hidden)")
    pg.wait_for_selector("#prNochmal", timeout=15000)


@pytest.mark.parametrize("schema", ["light", "dark"])
def test_360px_start_chat_ergebnis_hell_dunkel(browser, basis, schema):
    pg, fehler = _seite(browser, basis, 360, schema)
    assert pg.evaluate("matchMedia('(prefers-color-scheme: dark)').matches") == (schema == "dark")
    _kein_querscrollen(pg)
    assert pg.evaluate(KONTRAST_JS, ".pr-wahl span") >= 4.5
    pg.fill("#prFragen", "3")
    pg.click("#prStart")
    pg.wait_for_selector("#prAntwort")
    _kein_querscrollen(pg)
    pg.fill("#prAntwort", LANG)
    pg.click("#prSenden")
    pg.wait_for_selector(".pr-zeile.schueler")
    _kein_querscrollen(pg)
    assert pg.evaluate(KONTRAST_JS, ".pr-zeile.pruefer .pr-text") >= 4.5
    assert pg.evaluate(KONTRAST_JS, ".pr-zeile.schueler .pr-text") >= 4.5
    pg.click("#prBeenden")
    pg.click('#dlgForm button[value="ja"]')
    pg.wait_for_selector("#prNochmal")
    _kein_querscrollen(pg)
    for sel in (".pr-note", ".pr-note-name", ".pr-punkte"):
        assert pg.evaluate(KONTRAST_JS, sel) >= 4.5, sel
    assert pg.locator("#prNochmal").is_visible() and pg.locator("#prListe").is_visible()
    assert fehler == []


def test_tastatur_strg_enter_sendet_und_enter_nicht(browser, basis):
    pg, fehler = _seite(browser, basis)
    # Bedienung per Tab: Themen-Kontrollkästchen und Start sind erreichbar, Leertaste schaltet um
    pg.focus('input[name=thema]')
    vorher = pg.evaluate("document.activeElement.checked")
    pg.keyboard.press("Space")
    assert pg.evaluate("document.activeElement.checked") != vorher
    pg.keyboard.press("Space")
    pg.focus("#prFragen")
    pg.fill("#prFragen", "3")
    pg.keyboard.press("Enter")  # Enter im Formular startet
    pg.wait_for_selector("#prAntwort")
    pg.focus("#prAntwort")
    pg.keyboard.type(LANG)
    pg.keyboard.press("Enter")  # einfaches Enter = Zeilenumbruch, nicht senden
    assert pg.locator(".pr-zeile.schueler").count() == 0
    assert pg.input_value("#prAntwort").endswith("\n")
    pg.keyboard.press("Control+Enter")
    pg.wait_for_selector(".pr-zeile.schueler")
    assert LANG in pg.locator(".pr-zeile.schueler .pr-text").first.inner_text()
    assert fehler == []


def test_ganzer_lauf_per_tastatur_mit_note(browser, basis):
    pg, fehler = _seite(browser, basis)
    _bis_ergebnis(pg)
    assert pg.locator(".pr-note").inner_text().strip() in {"1", "2", "3", "4", "5"}
    assert fehler == []


def test_note_erscheint_in_der_liste(browser, basis):
    pg, fehler = _seite(browser, basis)
    _bis_ergebnis(pg)
    note = pg.locator(".pr-note").inner_text().strip()
    pg.click("#prListe")
    pg.wait_for_selector(".pr-eintrag")
    text = pg.locator(".pr-eintrag").first.inner_text()
    assert "Note" in text and "vorzeitig" not in text
    assert f"Note {note}" in text or note in text
    _kein_querscrollen(pg)
    assert fehler == []


def test_schritt_je_schalter(browser, basis, tmp_path):
    url, slug = basis
    pg = browser.new_context(viewport={"width": 1000, "height": 800}).new_page()
    pg.goto(f"{url}/ui/#/p/{slug}/vorschau")
    pg.wait_for_selector(".stepper")
    assert "Prüfung" in pg.inner_text(".stepper")
    # Schalter aus: derselbe Projektordner, kein Schritt und keine Route
    cfg = tmp_path / "aus.toml"
    cfg.write_text("[funktionen]\nki_einrichtung = false\npruefung = false\n", encoding="utf-8")
    port = _frei()
    env = {**os.environ, "GENUT_PROJEKTE": str(tmp_path / "projekte"), "GENUT_CONFIG": str(cfg)}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "genut.server:app", "--host", "127.0.0.1",
                             "--port", str(port), "--log-level", "warning"], cwd=WURZEL, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    aus = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(aus + "/api/gruppen", timeout=1).close()
                break
            except Exception:
                time.sleep(0.2)
        pg2 = browser.new_context(viewport={"width": 1000, "height": 800}).new_page()
        pg2.goto(f"{aus}/ui/#/p/{slug}/vorschau")
        pg2.wait_for_selector(".stepper")
        assert "Prüfung" not in pg2.inner_text(".stepper")
        try:
            urllib.request.urlopen(f"{aus}/api/projekte/{slug}/pruefungen", timeout=5)
            pytest.fail("Route sollte 404 liefern")
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        proc.terminate()
        proc.wait(5)
