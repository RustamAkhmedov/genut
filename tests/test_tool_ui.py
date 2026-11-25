"""Projektseite des Tools im Browser: 360 px ohne Querscrollen, Gruppe zuweisen, Ansicht bleibt (hell und dunkel)."""
import json
import shutil
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent


def _frei() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _api(basis: str, methode: str, pfad: str, daten: dict | None = None):
    req = urllib.request.Request(basis + "/api" + pfad, method=methode,
                                 data=json.dumps(daten).encode() if daten is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read() or "null")


@pytest.fixture
def tool(tmp_path):
    port = _frei()
    # ohne KI-Erkennung: der Server im eigenen Prozess darf keine echte CLI und nicht Google fragen (Constitution VII)
    cfg = tmp_path / "config.toml"
    cfg.write_text("[funktionen]\nki_einrichtung = false\n", encoding="utf-8")
    env = {**os.environ, "GENUT_PROJEKTE": str(tmp_path / "projekte"), "GENUT_CONFIG": str(cfg)}
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
        gruppe = _api(basis, "POST", "/gruppen", {"name": "Schularbeit Jänner"})
        projekte = [_api(basis, "POST", "/projekte", {"name": n, "fach": f})
                    for n, f in (("Integrale", "mathe"), ("Zellen", "chemie"), ("Alpha Test", "mathe"))]
        yield basis, gruppe, projekte
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(params=["light", "dark"])
def seite(request, tool):
    shot = pytest.importorskip("tests.shot")
    pfad = shot.browser_pfad()
    if pfad is None:
        pytest.skip("kein Chrome/Chromium gefunden")
    from playwright.sync_api import sync_playwright

    basis, gruppe, projekte = tool
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=pfad, args=["--no-sandbox"])
        ktx = b.new_context(viewport={"width": 360, "height": 800}, color_scheme=request.param)
        pg = ktx.new_page()
        fehler = []
        pg.on("pageerror", lambda e: fehler.append(str(e)))
        pg.goto(basis + "/ui/")
        pg.wait_for_selector(".karte.projekt")
        yield pg, gruppe, projekte, request.param
        assert fehler == []
        b.close()


def _kein_querscroll(pg):
    assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_360px_ohne_querscrollen(seite):
    pg, gruppe, projekte, schema = seite
    assert pg.evaluate("window.matchMedia('(prefers-color-scheme: %s)').matches" % schema)
    assert pg.evaluate("window.innerWidth") == 360
    _kein_querscroll(pg)
    pg.select_option("#modusSel", "fach")
    pg.wait_for_selector(".gruppe")
    _kein_querscroll(pg)


def test_gruppe_zuweisen(seite):
    pg, gruppe, projekte, _ = seite
    slug = projekte[0]["slug"]
    sel = pg.locator(f'.gruppen-wahl select[data-slug="{slug}"]')
    sel.select_option(gruppe["id"])
    pg.wait_for_selector(f'.gruppe[data-id="{gruppe["id"]}"] .karte.projekt')
    assert pg.locator(f'.gruppe[data-id="{gruppe["id"]}"] .karte.projekt').count() == 1
    assert pg.evaluate("location.hash") in ("", "#/", "#")
    assert _api(pg.url.split("/ui/")[0], "GET", f"/projekte/{slug}")["gruppe"] == gruppe["id"]
    pg.reload()
    pg.wait_for_selector(f'.gruppe[data-id="{gruppe["id"]}"] .karte.projekt')
    assert pg.locator(f'select[data-slug="{slug}"]').input_value() == gruppe["id"]
    _kein_querscroll(pg)


def test_ansicht_bleibt_nach_neuladen(seite):
    pg, *_ = seite
    pg.select_option("#modusSel", "fach")
    pg.wait_for_selector("#modusSel")
    pg.select_option("#sortSel", "name")
    pg.wait_for_function("JSON.parse(localStorage.getItem('genut.ansicht')).sortierung === 'name'")
    pg.reload()
    pg.wait_for_selector(".karte.projekt")
    assert pg.locator("#modusSel").input_value() == "fach"
    assert pg.locator("#sortSel").input_value() == "name"
    a = json.loads(pg.evaluate("localStorage.getItem('genut.ansicht')"))
    assert a["modus"] == "fach" and a["sortierung"] == "name"
    for abschnitt in pg.locator(".gruppe").all():
        namen = abschnitt.locator(".karte.projekt h3").all_inner_texts()
        assert namen == sorted(namen, key=str.lower)
    _kein_querscroll(pg)


def test_enter_im_gruppendialog_legt_an(seite):
    pg, *_ = seite
    basis = pg.url.split("/ui/")[0]
    pg.click("#gruppeNeuBtn")
    pg.fill("#gruppeName", "Enter Gruppe")
    pg.press("#gruppeName", "Enter")
    pg.wait_for_selector('.gruppe-name:text-is("Enter Gruppe")')
    assert "Enter Gruppe" in [g["name"] for g in _api(basis, "GET", "/gruppen")]


def test_formelsammlung_schritt(seite, tmp_path):
    if not (WURZEL / "node_modules" / "pdfkit").exists():
        pytest.skip("node_modules/pdfkit fehlt (npm install)")
    pg, *_ = seite
    basis = pg.url.split("/ui/")[0]
    p = _api(basis, "POST", "/projekte", {"name": "Formeln", "fach": "mathe"})
    ordner = tmp_path / "projekte" / p["slug"]
    shutil.copy(WURZEL / "tests" / "fixtures" / "integral" / "inhalt.json", ordner / "inhalt.json")
    (ordner / "out").mkdir(exist_ok=True)
    (ordner / "out" / "index.html").write_text("<html></html>", encoding="utf-8")

    pg.goto(f"{basis}/ui/#/p/{p['slug']}/formelsammlung")
    pg.wait_for_selector(".fs-zeile")
    _kein_querscroll(pg)

    # Häkchen und Schalter per Tastatur: Fokus auf das erste Häkchen, Leertaste wählt aus
    erste = pg.locator(".fs-zeile").first
    wahl = erste.locator(".fs-wahl input")
    wahl.focus()
    war = wahl.is_checked()
    pg.keyboard.press("Space")
    assert wahl.is_checked() != war
    schalter = erste.locator("[data-w]:not([disabled])")
    assert schalter.count() >= 1
    erster = schalter.first
    vorher = erster.is_checked()
    for _ in range(5):  # per Tab zum ersten Schalter dieser Zeile
        pg.keyboard.press("Tab")
        if erster.evaluate("e => e === document.activeElement"):
            break
    assert erster.evaluate("e => e === document.activeElement")
    pg.keyboard.press("Space")
    assert erster.is_checked() != vorher
    _kein_querscroll(pg)

    # PDF erstellen -> Herunterladen-Link
    pg.click("#fsPdf")
    pg.wait_for_selector('.fs-ergebnis a:has-text("Herunterladen")', timeout=60000)
    _kein_querscroll(pg)


HOOK_MODUL = """
export function start(hooks) {
  window.testHooks = { erlaubt: false, auftraege: [] };
  hooks.kiSchalter((knoepfe, status) => {
    const b = knoepfe[status.standard];
    b.classList.add('test-ki');
    b.onclick = () => { window.testHooks.geklickt = status.standard; };
  });
  hooks.vorAuftrag(async (a) => { window.testHooks.auftraege.push(a); return window.testHooks.erlaubt; });
  hooks.bereich('kopf-hinweis', (el) => {
    const p = document.createElement('p'); p.className = 'test-hinweis'; p.textContent = 'Test-Hinweis'; el.append(p);
  });
  hooks.bereich('test-stelle', (el, daten) => { el.textContent = daten.text; });
  const probe = document.createElement('div');
  hooks.bereichFuellen('test-stelle', probe, { text: 'gefüllt' });
  window.testHooks.probe = probe;
}
"""


def test_hooks_fuer_module(seite, tmp_path):
    pg, _, projekte, _ = seite
    basis = pg.url.split("/ui/")[0]
    p = projekte[0]
    shutil.copy(WURZEL / "tests" / "fixtures" / "integral" / "inhalt.json",
                tmp_path / "projekte" / p["slug"] / "inhalt.json")

    def ki(route):
        if route.request.method != "GET":
            return route.continue_()
        antwort = route.fetch()
        daten = antwort.json()
        daten["module"] = [*daten.get("module", []), "testhooks"]
        route.fulfill(response=antwort, json=daten)

    pg.route("**/api/ki", ki)
    pg.route("**/ui/funktionen/testhooks.js",
             lambda r: r.fulfill(content_type="text/javascript", body=HOOK_MODUL))
    posts = []

    def jobs(route):  # kein echter Auftrag: mitschneiden und ablehnen
        posts.append(route.request.post_data_json)
        route.fulfill(status=400, json={"detail": "Test: nicht gestartet"})

    pg.route("**/api/projekte/*/jobs", jobs)
    pg.goto(f"{basis}/ui/#/p/{p['slug']}/generieren")
    pg.reload()
    pg.wait_for_selector("#bauen:not([disabled])")

    # Schalter-Knopf bekommt eine Klasse, der Klick lässt sich ersetzen
    pg.wait_for_selector(".ki-schalter button.test-ki")
    pg.click(".ki-schalter button.test-ki")
    assert pg.evaluate("window.testHooks.geklickt")
    assert pg.evaluate("window.testHooks.probe.textContent") == "gefüllt"
    pg.wait_for_selector('[data-bereich="kopf-hinweis"] .test-hinweis')

    # vorAuftrag mit false: kein POST, keine Meldung, Oberfläche wie vorher
    pg.click("#bauen")
    pg.wait_for_function("window.testHooks.auftraege.length === 1")
    pg.wait_for_selector("#bauen:not([disabled])")
    assert posts == []
    assert pg.locator("#toast").is_hidden() and pg.locator("#fbar").is_hidden() and pg.locator("#log").is_hidden()
    assert pg.evaluate("window.testHooks.auftraege[0]") == {"art": "pruefen_bauen", "slug": p["slug"],
                                                           "modell": p["modell"]}

    # Gegenprobe mit true: der POST geht raus
    pg.evaluate("window.testHooks.erlaubt = true")
    pg.click("#bauen")
    pg.wait_for_selector('#toast:has-text("Test: nicht gestartet")')
    assert posts == [{"art": "pruefen_bauen"}]

    # nach einem Seitenwechsel wird die Stelle neu gefüllt, nicht doppelt
    pg.evaluate("location.hash = '#/'")
    pg.wait_for_selector(".karte.projekt")
    assert pg.locator('[data-bereich="kopf-hinweis"] .test-hinweis').count() == 1
    _kein_querscroll(pg)


BEREICH_MODUL = """
export function start(hooks) {
  window.testBereiche = { zeichnen: typeof hooks.diagrammeZeichnen };
  const marke = (el, name) => {
    const s = document.createElement('span'); s.className = 'marke-' + name; s.textContent = 'Marke'; el.append(s);
  };
  hooks.bereich('projektliste-aktionen', (el, { liste }) => {
    window.testBereiche.liste = liste.classList.contains('eng') && liste.parentElement.id === 'app' && liste.contains(el);
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'btn marke-projektliste-aktionen'; b.textContent = 'Importieren'; el.append(b);
  });
  hooks.bereich('projekt-chips', (el, p) => {
    marke(el, 'projekt-chips'); el.lastChild.dataset.passt = String(p.slug === el.dataset.slug);
  });
  hooks.bereich('export-herunterladen', async (el, { p, link }) => {
    window.testBereiche.link = link.id === 'dlLink' && link.getAttribute('href').includes(p.slug);
    marke(el, 'export-herunterladen');
  });
  hooks.bereich('fotos-hinweis', () => { throw new Error('absichtlich kaputt'); });
  hooks.bereich('fotos-hinweis', (el, p) => { marke(el, 'fotos-hinweis'); el.lastChild.dataset.slug = p.slug; });
}
"""


def test_bereiche_fuer_module(seite, tmp_path):
    pg, _, projekte, _ = seite
    slug = projekte[0]["slug"]
    ordner = tmp_path / "projekte" / slug
    shutil.copy(WURZEL / "tests" / "fixtures" / "integral" / "inhalt.json", ordner / "inhalt.json")
    (ordner / "out").mkdir(exist_ok=True)
    (ordner / "out" / "index.html").write_text("<html></html>", encoding="utf-8")

    def ki(route):
        if route.request.method != "GET":
            return route.continue_()
        antwort = route.fetch()
        daten = antwort.json()
        daten["module"] = ["testmodul"]  # echte Module belegen dieselben Stellen und verschöben das Layout
        route.fulfill(response=antwort, json=daten)

    anfragen = []
    pg.on("request", lambda r: anfragen.append(r)
          if r.resource_type == "fetch" and "/api/projekte" in r.url else None)
    pg.route("**/api/ki", ki)
    pg.route("**/ui/funktionen/testmodul.js",
             lambda r: r.fulfill(content_type="text/javascript", body=BEREICH_MODUL))
    pg.reload()

    # Projektliste: Knopf neben „Neues Projekt“ (auch bei 360 px), je Karte ein Marker
    pg.wait_for_selector(".kopfzeile .marke-projektliste-aktionen")
    pg.wait_for_selector(".karte.projekt .marke-projekt-chips")
    assert pg.evaluate("window.testBereiche.liste")
    assert pg.evaluate("window.testBereiche.zeichnen") == "function"
    assert pg.locator(".karte.projekt .reihe .marke-projekt-chips[data-passt='true']").count() == len(projekte)
    a = pg.locator(".marke-projektliste-aktionen").bounding_box()
    b = pg.locator("#neuBtn").bounding_box()
    assert abs(a["y"] - b["y"]) < 2 and a["x"] + a["width"] <= b["x"]
    _kein_querscroll(pg)

    # Fotos: ein Fehler wird gemeldet, die nächste Funktion und die Ansicht laufen weiter
    pg.evaluate(f"location.hash = '#/p/{slug}/fotos'")
    marke = f'[data-bereich="fotos-hinweis"] .marke-fotos-hinweis[data-slug="{slug}"]'
    pg.wait_for_selector(marke)
    pg.wait_for_selector('#toast.fehler:has-text("Modul: absichtlich kaputt")')
    assert pg.locator("#drop").is_visible()
    # nach dem Hochladen zeichnet der Tab neu und füllt wieder
    pg.set_input_files("#datei", files=[{"name": "notiz.md", "mimeType": "text/markdown", "buffer": b"# Notiz\n\nText"}])
    pg.wait_for_selector(".foto")
    pg.wait_for_selector(marke)
    assert pg.locator(".marke-fotos-hinweis").count() == 1
    _kein_querscroll(pg)

    pg.evaluate(f"location.hash = '#/p/{slug}/export'")
    pg.wait_for_selector('[data-bereich="export-herunterladen"] .marke-export-herunterladen')
    assert pg.evaluate("window.testBereiche.link")
    _kein_querscroll(pg)

    assert anfragen
    assert all(r.headers.get("x-genut") == "1" for r in anfragen), [(r.method, r.url) for r in anfragen]


def test_tool_formeln_ohne_links_und_fremdes_css(seite):
    """Formeln aus importierten Projekten dürfen auch in der Oberfläche nichts einschleusen (ui/tex_sicher.js)."""
    pg, *_ = seite
    pg.wait_for_function("window.MathJax && MathJax.typesetPromise")
    html = pg.evaluate(r"""async () => {
        const el = document.createElement('div');
        el.textContent = ['\\href{javascript:alert(1)}{a}', '\\mmlToken{mi}[href="javascript:alert(2)"]{b}',
          '\\require{html}\\href{javascript:alert(3)}{c}', '\\style{background:url(https://evil.example/a)}{d}',
          '\\colorbox{url(https://evil.example/b)}{e}', '\\cssId{app}{f}', '\\color{red}{g}'].map((t) => `\\(${t}\\)`).join(' ');
        document.body.appendChild(el);
        await MathJax.typesetPromise([el]);
        return [...el.querySelectorAll('*')].flatMap((k) => [...k.attributes]
          .filter((a) => a.name !== 'aria-label').map((a) => `${a.name}=${a.value}`)).join('\n');
    }""")
    assert "javascript:" not in html
    assert "evil.example" not in html
    assert "id=app" not in html.splitlines()
    assert "red" in html  # harmlose Farbe bleibt, Formeln wurden wirklich gesetzt
