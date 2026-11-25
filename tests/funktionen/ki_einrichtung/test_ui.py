"""KI-Schalter, Hinweis, Meldung vor einem Auftrag und Einrichten im Browser (T016, T019, SC-002, SC-003).

Server ist `fake_server` (keine CLI, kein Netz). Die 27 Kombinationen kommen als gemockte Antwort von
`/api/ki/zustaende`; ein Lauf nutzt zusätzlich die echte Route mit `GENUT_FAKE_KI`.
Beim Einrichten simuliert `fake_server` Installer, Download und Start; weil das seinen Zustand ändert,
bekommt jeder dieser Tests einen eigenen Server.
Wird ohne Chrome/Chromium übersprungen (wie tests/test_tool_ui.py)."""
import contextlib
import itertools
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import pytest

from genut.funktionen.ki_einrichtung.daten import modelle_laden
from genut.schema import Dokument

WURZEL = Path(__file__).resolve().parents[3]
FIX = WURZEL / "tests" / "fixtures" / "integral"

KIS = ("claude_code", "gemini", "ollama")
NAMEN = {"claude_code": "Claude", "gemini": "Gemini", "ollama": "Lokal"}
LANG = {**NAMEN, "ollama": "Lokal (experimentell)"}
ZUSTAENDE = ("bereit", "nicht_eingerichtet", "problem")
KLASSE = {"bereit": "ki-bereit", "nicht_eingerichtet": "ki-fehlt", "problem": "ki-problem"}
SYMBOL = {"bereit": None, "nicht_eingerichtet": "＋", "problem": "⚠"}
WORT = {"bereit": "bereit", "nicht_eingerichtet": "nicht eingerichtet", "problem": "Problem"}
URSACHE = {"bereit": "", "nicht_eingerichtet": "", "problem": "keine Antwort"}
SERVER_KI = "claude_code:bereit,gemini:problem,ollama:nicht_eingerichtet"
HINWEIS = '[data-bereich="kopf-hinweis"] .ki-hinweis'


def _frei() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def _fake_server(projekte: Path, **fake):
    """Startet `fake_server` mit den GENUT_FAKE_…-Werten aus `fake` und liefert seine Adresse."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GENUT_FAKE_")}
    env.update(GENUT_PROJEKTE=str(projekte), **fake)
    env.pop("GENUT_CONFIG", None)  # der Fake-Server nimmt dann eine Kopie von versionen/genut.toml
    port = _frei()
    proc = subprocess.Popen([sys.executable, "-m", "tests.funktionen.ki_einrichtung.fake_server", str(port)],
                            cwd=WURZEL, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    projekte = tmp_path_factory.mktemp("ki-ui") / "projekte"
    with _fake_server(projekte, GENUT_FAKE_KI=SERVER_KI) as url:
        yield url, projekte


@pytest.fixture
def fake(tmp_path):
    """fake(ki, dauer=…, fehler=…, rechner=…) -> Adresse eines frischen Fake-Servers."""
    laeufe = []

    def neu(ki: str, dauer: float = 1.5, fehler: str = "", rechner: str = "") -> str:
        lauf = _fake_server(tmp_path / "projekte", GENUT_FAKE_KI=ki, GENUT_FAKE_DAUER=str(dauer),
                            GENUT_FAKE_EINRICHTEN=fehler, GENUT_FAKE_RECHNER=rechner)
        url = lauf.__enter__()
        laeufe.append(lauf)
        return url

    yield neu
    for lauf in laeufe:
        lauf.__exit__(None, None, None)


@pytest.fixture
def projekt(server, monkeypatch):
    """Neues Projekt mit Inhalt, einem kontrollierten und einem noch nicht transkribierten Foto."""
    url, projekte = server
    monkeypatch.setenv("GENUT_PROJEKTE", str(projekte))
    from genut.projekt import Projekt
    from genut.schema import FotoEintrag

    p = Projekt.anlegen("KI Test")
    for datei in ("001.jpg", "002.jpg"):
        shutil.copy(FIX / "fotos" / "001.jpg", p.fotos / datei)
    p.inhalt_speichern(Dokument.model_validate_json((FIX / "inhalt.json").read_text(encoding="utf-8")))
    m = p.meta()
    m.fotos = [FotoEintrag(datei="001.jpg", original="a.jpg", status="kontrolliert"),
               FotoEintrag(datei="002.jpg", original="b.jpg")]
    p.meta_speichern(m)
    return p


@pytest.fixture(scope="module")
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


@pytest.fixture
def oeffnen(browser):
    """oeffnen(breite=…, schema=…) -> (seite, mitschnitt); prüft am Ende auf Skriptfehler."""
    kontexte, fehler = [], []

    def neu(breite=1000, schema="light"):
        ktx = browser.new_context(viewport={"width": breite, "height": 800}, color_scheme=schema)
        kontexte.append(ktx)
        pg = ktx.new_page()
        pg.on("pageerror", lambda e: fehler.append(str(e)))
        mitschnitt = {"jobs": [], "put": []}

        def jobs(route):  # kein echter Auftrag: mitschneiden und ablehnen
            mitschnitt["jobs"].append(route.request.post_data_json)
            route.fulfill(status=400, json={"detail": "Test: nicht gestartet"})

        pg.route("**/api/projekte/*/jobs", jobs)
        return pg, mitschnitt

    yield neu
    for ktx in kontexte:
        ktx.close()
    assert fehler == []


def _antwort(zustaende: dict) -> dict:
    jetzt = datetime.now().isoformat()
    liste = [{"name": n, "zustand": z, "ursache": URSACHE[z], "aktion": "", "auftrag": None, "geprueft": jetzt}
             for n, z in zustaende.items()]
    return {"zustaende": liste, "keine_bereit": all(z != "bereit" for z in zustaende.values())}


def _mock(pg, zustaende: dict):
    pg.route("**/api/ki/zustaende*", lambda r: r.fulfill(json=_antwort(zustaende)))


def _modell_setzen(projekt, modell: str):
    m = projekt.meta()
    m.modell = modell
    projekt.meta_speichern(m)


def _schalter_fertig(pg):
    pg.wait_for_function("""() => { const k = [...document.querySelectorAll('.ki-schalter [data-ki]')];
        return k.length === 3 && k.every(b => /ki-(bereit|fehlt|problem)/.test(b.className)); }""")


def _knopf(pg, name):
    return pg.locator(f'.ki-schalter [data-ki="{name}"]')


def _darstellung_pruefen(pg, zustaende: dict):
    for name, z in zustaende.items():
        knopf = _knopf(pg, name)
        klassen = knopf.get_attribute("class").split()
        assert [k for k in klassen if k in KLASSE.values()] == [KLASSE[z]], name
        symbole = knopf.locator(".ki-symbol").all_inner_texts()
        assert symbole == ([SYMBOL[z]] if SYMBOL[z] else []), name
        erwartet = f"{LANG[name]}: {WORT[z]}" + (f", {URSACHE[z]}" if URSACHE[z] else "")
        assert knopf.get_attribute("aria-label") == erwartet
        assert knopf.get_attribute("aria-haspopup") == (None if z == "bereit" else "dialog"), name
        assert knopf.get_attribute("title"), name
        assert knopf.locator(".ki-exp").count() == (1 if name == "ollama" else 0)


@pytest.mark.parametrize("kombination", list(itertools.product(ZUSTAENDE, repeat=3)),
                         ids=lambda k: "-".join(z[0] for z in k))
def test_alle_kombinationen(server, oeffnen, kombination):
    url, _ = server
    zustaende = dict(zip(KIS, kombination))
    pg, mitschnitt = oeffnen()
    _mock(pg, zustaende)

    def ki(route):  # PUT mitschneiden; die Zustände des Servers passen nicht zur gemockten Antwort
        if route.request.method != "PUT":
            return route.continue_()
        mitschnitt["put"].append(route.request.post_data_json["standard"])
        route.fulfill(json={})

    pg.route("**/api/ki", ki)
    pg.goto(url + "/ui/")
    _schalter_fertig(pg)
    _darstellung_pruefen(pg, zustaende)
    assert pg.locator(HINWEIS).count() == (0 if "bereit" in kombination else 1)

    # nur bereite KIs sind umschaltbar, die anderen öffnen den Dialog
    erwartet = []
    for name, z in zustaende.items():
        _schalter_fertig(pg)
        if z == "bereit":
            with pg.expect_request(lambda r: r.method == "PUT" and r.url.endswith("/api/ki")):
                _knopf(pg, name).click()
            pg.wait_for_selector(f'#toast:has-text("{NAMEN[name]}")')
            assert pg.locator(".ki-dlg[open]").count() == 0
            erwartet.append(name)
        else:
            _knopf(pg, name).click()
            pg.wait_for_selector(".ki-dlg[open]")
            assert pg.inner_text(".ki-dlg h2") == f"{NAMEN[name]} einrichten"
            pg.click('.ki-dlg button:text-is("Schließen")')
            pg.wait_for_selector(".ki-dlg[open]", state="detached")
        assert mitschnitt["put"] == erwartet, name


def test_echte_route_mit_fake_zustaenden(server, oeffnen):
    """Ohne Mock: Claude bereit, Gemini Problem, Lokal nicht eingerichtet; nur Claude ist umschaltbar."""
    url, _ = server
    pg, mitschnitt = oeffnen()
    pg.on("request", lambda r: r.method == "PUT" and r.url.endswith("/api/ki")
          and mitschnitt["put"].append(r.post_data_json["standard"]))
    pg.goto(url + "/ui/")
    _schalter_fertig(pg)
    for name, z in zip(KIS, ("bereit", "problem", "nicht_eingerichtet")):
        assert KLASSE[z] in _knopf(pg, name).get_attribute("class").split()
    for name in ("gemini", "ollama"):
        _knopf(pg, name).click()
        pg.wait_for_selector(".ki-dlg[open]")
        pg.keyboard.press("Escape")
        pg.wait_for_selector(".ki-dlg[open]", state="detached")
    assert mitschnitt["put"] == []
    _knopf(pg, "claude_code").click()
    pg.wait_for_selector('.ki-schalter [data-ki="claude_code"][aria-checked="true"]')
    assert mitschnitt["put"] == ["claude_code"]
    assert pg.locator(HINWEIS).count() == 0


def _auftrag_klicken(pg, url, slug, tab, knopf):
    pg.goto(f"{url}/ui/#/p/{slug}/{tab}")
    pg.wait_for_selector(f"{knopf}:not([disabled])")
    pg.click(knopf)


@pytest.mark.parametrize("tab, knopf", [("generieren", "#gen"), ("fotos", "#tkBtn")])
def test_keine_ki_bereit_hinweis_und_kein_auftrag(server, projekt, oeffnen, tab, knopf):
    url, _ = server
    pg, mitschnitt = oeffnen()
    _mock(pg, {"claude_code": "nicht_eingerichtet", "gemini": "problem", "ollama": "nicht_eingerichtet"})
    pg.goto(f"{url}/ui/#/p/{projekt.slug}/{tab}")
    pg.wait_for_selector(HINWEIS)
    assert "Richte zuerst eine KI ein" in pg.inner_text(HINWEIS)
    # Verweis auf den Schalter: Fokus landet auf dem ersten Knopf
    pg.click(f"{HINWEIS} button")
    assert pg.evaluate("document.activeElement.dataset.ki") == "claude_code"
    _auftrag_klicken(pg, url, projekt.slug, tab, knopf)
    pg.wait_for_selector(".ki-dlg[open]")
    assert pg.inner_text(".ki-dlg h2") == "Richte zuerst eine KI ein"
    for name in NAMEN.values():
        assert pg.locator(f'.ki-dlg button:text-is("{name} einrichten")').count() == 1
    pg.click('.ki-dlg button:text-is("Schließen")')
    pg.wait_for_selector(f"{knopf}:not([disabled])")  # Oberfläche wie vorher
    assert mitschnitt["jobs"] == []
    assert pg.locator("#toast").is_hidden() and pg.locator("#fbar").is_hidden() and pg.locator("#log").is_hidden()


def test_nur_pruefen_und_bauen_wird_nie_gesperrt(server, projekt, oeffnen):
    url, _ = server
    pg, mitschnitt = oeffnen()
    _mock(pg, dict.fromkeys(KIS, "nicht_eingerichtet"))
    _auftrag_klicken(pg, url, projekt.slug, "generieren", "#bauen")
    pg.wait_for_selector('#toast:has-text("Test: nicht gestartet")')
    assert mitschnitt["jobs"] == [{"art": "pruefen_bauen"}]
    assert pg.locator(".ki-dlg[open]").count() == 0


def test_projekt_mit_nicht_bereiter_ki_dialog_statt_auftrag(server, projekt, oeffnen):
    """Echte Route (GENUT_FAKE_KI): Dialog, Wechsel zu bereiter KI, danach startet der Auftrag."""
    url, _ = server
    _modell_setzen(projekt, "gemini")
    pg, mitschnitt = oeffnen()
    _auftrag_klicken(pg, url, projekt.slug, "generieren", "#gen")
    pg.wait_for_selector(".ki-dlg[open]")
    assert pg.inner_text(".ki-dlg h2") == "Gemini ist nicht bereit"
    assert "Schlüssel wird nicht akzeptiert" in pg.inner_text(".ki-dlg")
    assert pg.locator(".ki-dlg button").all_inner_texts() == ["Abbrechen", "Gemini einrichten", "Zu Claude wechseln"]
    pg.click('.ki-dlg button:text-is("Abbrechen")')
    pg.wait_for_selector("#gen:not([disabled])")
    assert mitschnitt["jobs"] == [] and projekt.meta().modell == "gemini"

    pg.click("#gen")
    pg.click('.ki-dlg button:text-is("Gemini einrichten")')
    pg.wait_for_selector('.ki-dlg h2:text-is("Gemini einrichten")')
    pg.keyboard.press("Escape")
    assert mitschnitt["jobs"] == []

    pg.wait_for_selector("#gen:not([disabled])")
    pg.click("#gen")
    pg.click('.ki-dlg button:text-is("Zu Claude wechseln")')
    pg.wait_for_selector('#toast:has-text("KI dieses Projekts: Claude")')
    pg.wait_for_selector('.ki-schalter [data-ki="claude_code"][aria-checked="true"]')
    assert projekt.meta().modell == "claude_code"
    assert mitschnitt["jobs"] == []  # der Wechsel startet nichts von selbst
    pg.wait_for_selector("#gen:not([disabled])")
    pg.click("#gen")
    pg.wait_for_selector('#toast:has-text("Test: nicht gestartet")')
    assert mitschnitt["jobs"] == [{"art": "generieren"}]


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


def _passt_in_die_breite(pg, auswahl: str):
    assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    for kasten in (e.bounding_box() for e in pg.locator(auswahl).all()):
        assert kasten and kasten["x"] >= 0 and kasten["x"] + kasten["width"] <= 360, (auswahl, kasten)


@pytest.mark.parametrize("schema", ["light", "dark"])
@pytest.mark.parametrize("zustaende", [("bereit", "problem", "nicht_eingerichtet"),
                                       ("problem", "problem", "problem"),
                                       ("nicht_eingerichtet",) * 3], ids=lambda k: "-".join(z[0] for z in k))
def test_360px_hell_dunkel(server, projekt, oeffnen, schema, zustaende):
    url, _ = server
    _modell_setzen(projekt, "gemini")
    pg, mitschnitt = oeffnen(360, schema)
    zustaende = dict(zip(KIS, zustaende))
    _mock(pg, zustaende)
    for ziel in ("", f"p/{projekt.slug}/generieren"):
        pg.goto(f"{url}/ui/#/{ziel}")
        pg.wait_for_selector("#gen" if ziel else ".karte.projekt")
        _schalter_fertig(pg)
        if "bereit" not in zustaende.values():
            pg.wait_for_selector(HINWEIS)
            _passt_in_die_breite(pg, f"{HINWEIS}, {HINWEIS} button")
            assert pg.evaluate(KONTRAST_JS, f"{HINWEIS} p") >= 4.5
        _passt_in_die_breite(pg, ".ki-schalter [data-ki]")
    assert pg.evaluate("matchMedia('(prefers-color-scheme: dark)').matches") == (schema == "dark")
    pg.wait_for_selector("#gen:not([disabled])")
    pg.click("#gen")  # Dialog vor dem Auftrag
    pg.wait_for_selector(".ki-dlg[open]")
    _passt_in_die_breite(pg, ".ki-dlg, .ki-dlg button")
    assert pg.evaluate(KONTRAST_JS, ".ki-dlg-inhalt p") >= 4.5
    pg.keyboard.press("Escape")
    pg.wait_for_selector(".ki-dlg[open]", state="detached")
    _knopf(pg, "gemini").click()  # Dialog „einrichten“
    pg.wait_for_selector(".ki-dlg[open] .ki-ursache")
    _passt_in_die_breite(pg, ".ki-dlg, .ki-dlg button, .ki-ursache")
    assert pg.evaluate(KONTRAST_JS, ".ki-ursache strong") >= 4.5
    assert mitschnitt["jobs"] == []


def test_tastatur_und_sichtbarer_fokus(server, oeffnen):
    url, _ = server
    pg, _ = oeffnen(360)
    pg.goto(url + "/ui/")
    _schalter_fertig(pg)
    _knopf(pg, "claude_code").focus()
    pg.keyboard.press("Tab")
    assert pg.evaluate("document.activeElement.dataset.ki") == "gemini"
    assert pg.evaluate("""(() => { const s = getComputedStyle(document.activeElement);
        return (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== 'none'; })()""")
    pg.keyboard.press("Enter")
    pg.wait_for_selector(".ki-dlg[open]")
    assert pg.evaluate("document.activeElement.type") == "password"  # Gemini: direkt ins Schlüsselfeld
    pg.keyboard.press("Escape")
    pg.wait_for_selector(".ki-dlg[open]", state="detached")
    pg.wait_for_function("document.activeElement.dataset.ki === 'gemini'", timeout=3000)


def test_fokus_bleibt_beim_neuzeichnen_des_schalters(server, oeffnen):
    url, _ = server
    pg, _ = oeffnen(1000)
    pg.goto(url + "/ui/")
    _schalter_fertig(pg)
    _knopf(pg, "gemini").focus()
    pg.evaluate("window.__alt = document.activeElement; window.dispatchEvent(new HashChangeEvent('hashchange'))")
    pg.wait_for_function("!window.__alt.isConnected")
    _schalter_fertig(pg)
    assert pg.evaluate("document.activeElement.dataset.ki") == "gemini"


# ---------------------------------------------------------------- Einrichten (T019)

FRIST = 5.0  # SC-003: so schnell ist die KI nach dem Einrichten ohne Neustart als bereit zu sehen
VORSCHLAEGE = [m.name for m in modelle_laden()]
RADIOS = '.ki-dlg input[name="kiModell"]'
SENDEN = '.ki-dlg form button[type="submit"]'
BALKEN = ".ki-dlg [role=progressbar]"


def _starten(pg, url):
    """Öffnet die App und merkt sich die Seite, damit ein Neuladen auffiele."""
    pg.goto(url + "/ui/")
    _schalter_fertig(pg)
    pg.evaluate("window.__ohneNeustart = true")


def _dialog_oeffnen(pg, name):
    _knopf(pg, name).click()
    pg.wait_for_selector(".ki-dlg[open]")


def _dialog_schliessen(pg):
    pg.keyboard.press("Escape")
    pg.wait_for_selector(".ki-dlg[open]", state="detached")


def _bereit_sichtbar(pg, name, seit: float, frist: float = FRIST):
    rest = max(1, (seit + frist - time.monotonic()) * 1000)
    pg.wait_for_selector(f'.ki-schalter [data-ki="{name}"].ki-bereit', timeout=rest)
    assert time.monotonic() - seit <= frist
    assert pg.evaluate("window.__ohneNeustart") is True  # ohne Neuladen


def _api(url, pfad):
    with urllib.request.urlopen(url + "/api" + pfad, timeout=10) as antwort:
        return json.load(antwort)


def _zustand(url, name):
    return next(z for z in _api(url, "/ki/zustaende")["zustaende"] if z["name"] == name)


def _posts(pg, ende: str) -> list:
    liste = []
    pg.on("request", lambda r: r.method == "POST" and r.url.endswith(ende) and liste.append(r.url))
    return liste


def test_gemini_abgelehnt_offline_dann_gueltig_ist_bereit(fake, oeffnen):
    url = fake("")
    pg, _ = oeffnen()
    _starten(pg, url)
    pg.wait_for_selector(HINWEIS)
    _dialog_oeffnen(pg, "gemini")
    feld = pg.locator(".ki-dlg input.ki-eingabe")
    assert pg.locator(".ki-dlg a").get_attribute("rel") == "noopener noreferrer"
    for eingabe, meldung in (("abgelehnt-123", "Schlüssel wird nicht akzeptiert"),
                             ("offline-123", "Keine Verbindung zu Google")):
        feld.fill(eingabe)
        feld.press("Enter")
        pg.wait_for_selector(f'.ki-dlg form .ki-fehler:has-text("{meldung}")')
        assert feld.input_value() == eingabe  # Feld und Eingabe bleiben
        assert feld.get_attribute("aria-invalid") == "true"
        assert pg.evaluate("document.activeElement.type") == "password"
        assert "ki-bereit" not in _knopf(pg, "gemini").get_attribute("class")
    feld.fill("gueltiger-schluessel-123")
    seit = time.monotonic()
    feld.press("Enter")
    _bereit_sichtbar(pg, "gemini", seit)
    pg.wait_for_selector('.ki-dlg .ki-ursache.ki-bereit:has-text("Gemini ist bereit")')
    assert "gueltiger-schluessel" not in pg.content()
    pg.wait_for_selector(HINWEIS, state="detached")
    _dialog_schliessen(pg)
    _knopf(pg, "gemini").click()  # jetzt umschaltbar
    pg.wait_for_selector('.ki-schalter [data-ki="gemini"][aria-checked="true"]')


def test_lokal_vorschlaege_fortschritt_schliessen_und_oeffnen(fake, oeffnen):
    url = fake("ollama:ohne_modell", dauer=2.5)
    pg, _ = oeffnen()
    posts = _posts(pg, "/api/ki/ollama/modell")
    _starten(pg, url)
    _dialog_oeffnen(pg, "ollama")
    pg.wait_for_selector(RADIOS)
    namen = [r.get_attribute("value") for r in pg.locator(RADIOS).all()]
    assert namen == [*VORSCHLAEGE, "llava:7b"]
    assert pg.locator(".ki-dlg fieldset").first.locator("input").count() == 3
    assert pg.locator(".ki-dlg fieldset").first.locator(".chip").count() >= 3  # Urteil je Vorschlag
    assert pg.locator(f"{RADIOS}:checked").count() == 1
    assert pg.inner_text(SENDEN) == "Laden"
    seit = time.monotonic()
    pg.click(SENDEN)
    pg.wait_for_selector(f"{BALKEN}[aria-valuenow]")
    erster = int(pg.get_attribute(BALKEN, "aria-valuenow"))
    assert 0 <= erster <= 100 and pg.locator(".ki-dlg .ki-prozent").is_visible()

    _dialog_schliessen(pg)
    pg.wait_for_function("""() => document.querySelector('.ki-schalter [data-ki="ollama"]')
        .getAttribute('aria-label').includes('Einrichtung läuft')""")
    _dialog_oeffnen(pg, "ollama")
    pg.wait_for_selector(f"{BALKEN}[aria-valuenow]")  # derselbe Auftrag, kein neues Formular
    assert int(pg.get_attribute(BALKEN, "aria-valuenow")) >= erster
    assert pg.locator(RADIOS).count() == 0
    assert pg.locator('.ki-dlg button:text-is("Erneut prüfen")').is_hidden()
    assert pg.evaluate("!!document.activeElement.closest('.ki-dlg')")

    _bereit_sichtbar(pg, "ollama", seit)
    pg.wait_for_selector('.ki-dlg .ki-ursache.ki-bereit:has-text("Lokal ist bereit")')
    assert len(posts) == 1


def test_lokal_bei_geschlossenem_dialog_fertig_ist_beim_oeffnen_des_schalters_bereit(fake, oeffnen):
    url = fake("ollama:ohne_modell", dauer=1.5)
    pg, _ = oeffnen()
    _starten(pg, url)
    _dialog_oeffnen(pg, "ollama")
    pg.wait_for_selector(RADIOS)
    with pg.expect_response(lambda r: r.url.endswith("/api/ki/ollama/modell")) as antwort:
        pg.click(SENDEN)
    kennung = antwort.value.json()["auftrag"]
    _dialog_schliessen(pg)
    for _ in range(100):
        if _api(url, f"/ki/auftraege/{kennung}")["status"] == "fertig":
            break
        time.sleep(0.1)
    else:
        pytest.fail("Auftrag wird nicht fertig")
    seit = time.monotonic()
    pg.locator(".ki-schalter").dispatch_event("pointerenter")  # „Öffnen“ des Schalters
    _bereit_sichtbar(pg, "ollama", seit)


def test_vorhandenes_modell_ist_sofort_bereit(fake, oeffnen):
    url = fake("ollama:ohne_modell")
    pg, _ = oeffnen()
    _starten(pg, url)
    _dialog_oeffnen(pg, "ollama")
    pg.wait_for_selector(RADIOS)
    pg.check(f'{RADIOS}[value="llava:7b"]')
    assert pg.inner_text(SENDEN) == "Verwenden"
    seit = time.monotonic()
    with pg.expect_response(lambda r: r.url.endswith("/api/ki/ollama/modell")) as antwort:
        pg.click(SENDEN)
    assert antwort.value.status == 200 and antwort.value.json()["zustand"] == "bereit"  # kein Download
    _bereit_sichtbar(pg, "ollama", seit)
    assert _zustand(url, "ollama")["zustand"] == "bereit"


def test_ollama_starten_dann_modell_laden(fake, oeffnen):
    url = fake("ollama:problem", dauer=1)
    pg, _ = oeffnen()
    _starten(pg, url)
    _dialog_oeffnen(pg, "ollama")
    pg.click('.ki-dlg button:text-is("Ollama starten")')
    pg.wait_for_selector(RADIOS)
    seit = time.monotonic()
    pg.click(SENDEN)
    _bereit_sichtbar(pg, "ollama", seit)


def test_schwacher_rechner_empfiehlt_gemini(fake, oeffnen):
    url = fake("ollama:ohne_modell", rechner="schwach")
    pg, _ = oeffnen()
    _starten(pg, url)
    _dialog_oeffnen(pg, "ollama")
    pg.wait_for_selector(RADIOS)
    assert "Gemini empfohlen" in pg.inner_text(".ki-dlg .ki-warnung")
    assert pg.locator(".ki-dlg fieldset").first.locator("input").count() == 3
    assert pg.locator(".ki-dlg .chip.ok").count() == 0


def test_download_fehler_nochmal_versuchen_laedt_dasselbe_modell(fake, oeffnen):
    url = fake("ollama:ohne_modell", dauer=1, fehler="fehler_einmal")
    pg, _ = oeffnen()
    gesendet = []
    pg.on("request", lambda r: r.method == "POST" and r.url.endswith("/api/ki/ollama/modell")
          and gesendet.append(r.post_data_json["name"]))
    _starten(pg, url)
    _dialog_oeffnen(pg, "ollama")
    pg.wait_for_selector(RADIOS)
    vorwahl = pg.locator(f"{RADIOS}:checked").get_attribute("value")
    anderes = next(n for n in VORSCHLAEGE if n != vorwahl)
    pg.check(f'{RADIOS}[value="{anderes}"]')
    pg.click(SENDEN)
    pg.wait_for_selector('.ki-dlg [role=alert]:has-text("Simulierter Fehler")')
    pg.wait_for_selector(f'{SENDEN}:text-is("Nochmal versuchen")')
    assert pg.locator(f"{RADIOS}:checked").get_attribute("value") == anderes
    assert _zustand(url, "ollama")["zustand"] != "bereit"  # halbes Modell zählt nicht
    assert "ki-bereit" not in _knopf(pg, "ollama").get_attribute("class")
    pg.check(f'{RADIOS}[value="{vorwahl}"]')  # eine andere Wahl heißt wieder wie sonst
    assert pg.inner_text(SENDEN) == "Laden"
    pg.check(f'{RADIOS}[value="{anderes}"]')
    seit = time.monotonic()
    pg.click(SENDEN)
    _bereit_sichtbar(pg, "ollama", seit)
    assert pg.locator('.ki-dlg :text("Simulierter Fehler")').count() == 0
    assert gesendet == [anderes, anderes]


@pytest.mark.parametrize("ki, stand, aktion, pfad", [
    ("claude_code", "nicht_eingerichtet", "Claude installieren", "/api/ki/claude/installieren"),
    ("ollama", "problem", "Ollama starten", "/api/ki/ollama/starten")], ids=["claude", "ollama-start"])
def test_fehler_nochmal_versuchen_startet_neuen_auftrag(fake, oeffnen, ki, stand, aktion, pfad):
    url = fake(f"{ki}:{stand}", dauer=0.6, fehler="fehler")
    pg, _ = oeffnen()
    posts = _posts(pg, pfad)
    _starten(pg, url)
    _dialog_oeffnen(pg, ki)
    pg.click(f'.ki-dlg button:text-is("{aktion}")')
    nochmal = '.ki-dlg button:text-is("Nochmal versuchen")'
    for versuch in (1, 2):
        pg.wait_for_selector('.ki-dlg [role=alert]:has-text("Simulierter Fehler")')
        pg.wait_for_selector(nochmal)
        assert len(posts) == versuch
        assert pg.evaluate("document.activeElement.textContent") == "Nochmal versuchen"
        if versuch == 1:
            pg.keyboard.press("Enter")
            pg.wait_for_selector(BALKEN)
    pg.click('.ki-dlg button:text-is("Erneut prüfen")')  # danach heißt die Aktion wieder wie sonst
    pg.wait_for_selector(f'.ki-dlg button:text-is("{aktion}")')


def test_claude_installieren_dann_anmelde_hinweis(fake, oeffnen):
    url = fake("", dauer=2)
    pg, _ = oeffnen()
    _starten(pg, url)
    _dialog_oeffnen(pg, "claude_code")
    pg.click('.ki-dlg button:text-is("Claude installieren")')
    pg.wait_for_selector('.ki-dlg .ki-ausgabe:has-text("Lade Claude Code")')
    pg.wait_for_selector(".ki-dlg .ki-anleitung")
    assert "Öffne ein Terminal, gib claude ein" in pg.inner_text(".ki-dlg .ki-anleitung")
    assert pg.locator(".ki-dlg button").all_inner_texts() == ["Schließen", "Erneut prüfen"]
    assert pg.locator(".ki-dlg [role=alert]").count() == 0
    pg.wait_for_selector('.ki-schalter [data-ki="claude_code"].ki-problem')


def test_claude_nicht_angemeldet_zeigt_nur_den_hinweis(fake, oeffnen):
    url = fake("claude_code:problem")
    pg, _ = oeffnen()
    posts = _posts(pg, "/api/ki/claude/installieren")
    _starten(pg, url)
    _dialog_oeffnen(pg, "claude_code")
    pg.wait_for_selector(".ki-dlg .ki-anleitung")
    assert pg.locator(".ki-dlg button").all_inner_texts() == ["Schließen", "Erneut prüfen"]
    pg.click('.ki-dlg button:text-is("Erneut prüfen")')
    pg.wait_for_selector('.ki-dlg button:text-is("Erneut prüfen"):not([aria-disabled])')
    assert pg.locator(".ki-dlg .ki-anleitung").count() == 1 and posts == []


def _fokus(pg, bedingung: str) -> bool:
    return pg.evaluate(f"(() => {{ const f = document.activeElement; return {bedingung}; }})()")


def _fokus_auf_knopf(pg, name):
    pg.wait_for_function("name => document.activeElement.dataset.ki === name", arg=name, timeout=3000)


def test_fokus_kehrt_zurueck_auch_wenn_der_schalter_bei_offenem_dialog_neu_gezeichnet_wird(server, oeffnen):
    url, _ = server
    pg, _ = oeffnen()
    pg.goto(url + "/ui/")
    _schalter_fertig(pg)
    _knopf(pg, "ollama").focus()
    pg.keyboard.press("Enter")
    pg.wait_for_selector(".ki-dlg[open]")
    pg.evaluate("""window.__alt = document.querySelector('.ki-schalter [data-ki="ollama"]');
        window.dispatchEvent(new HashChangeEvent('hashchange'))""")
    pg.wait_for_function("!window.__alt.isConnected")
    _dialog_schliessen(pg)
    _fokus_auf_knopf(pg, "ollama")


def test_lokal_einrichten_nur_mit_der_tastatur(fake, oeffnen):
    url = fake("ollama:ohne_modell", dauer=1.5)
    pg, _ = oeffnen()
    _starten(pg, url)
    _knopf(pg, "ollama").focus()
    pg.keyboard.press("Enter")
    pg.wait_for_selector(RADIOS)
    for _ in range(8):  # rückwärts bis in die Modellwahl
        if _fokus(pg, "f.name === 'kiModell'"):
            break
        pg.keyboard.press("Shift+Tab")
    assert _fokus(pg, "f.name === 'kiModell' && f.checked")
    vorher = pg.evaluate("document.activeElement.value")
    pg.keyboard.press("ArrowDown")
    assert _fokus(pg, f"f.name === 'kiModell' && f.checked && f.value !== '{vorher}'")
    seit = time.monotonic()
    pg.keyboard.press("Enter")
    pg.wait_for_selector(BALKEN)
    assert _fokus(pg, "!!f.closest('.ki-dlg')")
    _bereit_sichtbar(pg, "ollama", seit)
    pg.wait_for_selector(".ki-dlg .ki-ursache.ki-bereit")
    assert _fokus(pg, "!!f.closest('.ki-dlg')")
    _dialog_schliessen(pg)
    _fokus_auf_knopf(pg, "ollama")


@pytest.mark.parametrize("schema", ["light", "dark"])
def test_einrichten_bei_360px(fake, oeffnen, schema):
    url = fake("ollama:ohne_modell,claude_code:problem", dauer=2, fehler="fehler_einmal")
    pg, _ = oeffnen(360, schema)
    _starten(pg, url)
    alles = ".ki-dlg, .ki-dlg button"

    def passt(auswahl):  # nur Sichtbares: während eines Auftrags ist „Erneut prüfen“ versteckt
        assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        kaesten = pg.eval_on_selector_all(auswahl, """alle => alle.filter(e => e.checkVisibility())
            .map(e => { const k = e.getBoundingClientRect(); return [k.left, k.right]; })""")
        assert kaesten and all(links >= 0 and rechts <= 360 for links, rechts in kaesten), (auswahl, kaesten)
        assert pg.evaluate("""[...document.querySelectorAll('.ki-dlg, .ki-dlg-box')]
            .every(e => e.scrollWidth <= e.clientWidth)""")

    _dialog_oeffnen(pg, "gemini")
    pg.fill(".ki-dlg input.ki-eingabe", "abgelehnt")
    pg.press(".ki-dlg input.ki-eingabe", "Enter")
    pg.wait_for_selector(".ki-dlg form .ki-fehler:not([hidden])")
    passt(f"{alles}, .ki-dlg input, .ki-dlg .ki-fehler")
    _dialog_schliessen(pg)

    _dialog_oeffnen(pg, "claude_code")
    pg.wait_for_selector(".ki-dlg .ki-anleitung")
    passt(f"{alles}, .ki-dlg .ki-anleitung")
    _dialog_schliessen(pg)

    _dialog_oeffnen(pg, "ollama")
    pg.wait_for_selector(RADIOS)
    passt(f"{alles}, .ki-dlg .ki-modell")
    pg.click(SENDEN)
    pg.wait_for_selector(f"{BALKEN}[aria-valuenow]")
    passt(f"{alles}, {BALKEN}, .ki-dlg .ki-prozent")
    pg.wait_for_selector(f'{SENDEN}:text-is("Nochmal versuchen")')
    passt(f"{alles}, .ki-dlg .ki-modell, .ki-dlg [role=alert]:not([hidden])")
