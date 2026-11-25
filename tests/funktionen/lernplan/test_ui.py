"""Lernplan im Browser: 360 px ohne Querscrollen, Plan per Tastatur anlegen, Abhaken, hell/dunkel, Menüpunkt je Schalter."""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[3]


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


@contextmanager
def _server(tmp_path, lernplan: bool):
    port = _frei()
    cfg = tmp_path / f"config_{lernplan}.toml"
    cfg.write_text(f"[funktionen]\nki_einrichtung = false\nlernplan = {'true' if lernplan else 'false'}\n", encoding="utf-8")
    env = {**os.environ, "GENUT_PROJEKTE": str(tmp_path / f"projekte_{lernplan}"), "GENUT_CONFIG": str(cfg)}
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
        p = _api(basis, "POST", "/projekte", {"name": "Integrale", "fach": "mathe"})
        slug = p.get("slug") or p["id"]
        shutil.copy(WURZEL / "tests/fixtures/integral/inhalt.json",
                    tmp_path / f"projekte_{lernplan}" / slug / "inhalt.json")
        yield basis, slug
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _browser(farbschema: str):
    shot = pytest.importorskip("tests.shot")
    pfad = shot.browser_pfad()
    if pfad is None:
        pytest.skip("kein Chrome/Chromium gefunden")
    pytest.importorskip("playwright")
    return pfad


def _quer(pg) -> bool:
    return pg.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")


@pytest.fixture(params=["light", "dark"])
def seite(request, tmp_path):
    pfad = _browser(request.param)
    from playwright.sync_api import sync_playwright

    with _server(tmp_path, True) as (basis, slug), sync_playwright() as p:
        b = p.chromium.launch(executable_path=pfad, args=["--no-sandbox"])
        pg = b.new_context(viewport={"width": 360, "height": 800}, color_scheme=request.param).new_page()
        pg.set_default_timeout(10000)
        fehler = []
        pg.on("pageerror", lambda e: fehler.append(str(e)))
        pg.on("console", lambda m: fehler.append(m.text) if m.type == "error" else None)
        yield pg, basis, slug, request.param
        b.close()
        assert fehler == []


def test_liste_anlegen_per_tastatur_abhaken(seite):
    pg, basis, slug, schema = seite
    termin = (date.today() + timedelta(days=10)).isoformat()
    assert pg.evaluate("matchMedia('(prefers-color-scheme: dark)').matches") == (schema == "dark")

    pg.goto(basis + "/#/lernplan")
    pg.wait_for_selector("#lpNeu")
    assert pg.locator(".lp-plan").count() == 0
    assert not _quer(pg)

    # Anlegen nur mit Tastatur: Fokus auf den Knopf (wie per Tab), Enter, Tippen, Enter auf „Plan anlegen“
    pg.focus("#lpNeu")
    pg.keyboard.press("Enter")
    pg.wait_for_selector("#dlg[open]")
    assert pg.evaluate("document.querySelector('#dlg').contains(document.activeElement)")
    assert not _quer(pg)
    pg.focus("[name=name]")
    pg.keyboard.type("Tastatur-Plan")
    pg.fill("[name=termin]", termin)
    # neuer Plan: kein Projekt vorausgewählt, Start steht vor dem Prüfungstermin
    assert pg.locator("[data-projekt]:checked").count() == 0
    assert pg.evaluate("[...document.querySelectorAll('#dlgForm input[type=date]')].map(e => e.name)") == ["start", "termin"]
    pg.locator("[data-projekt]").first.check()
    pg.focus("#lpSpeichern")
    pg.keyboard.press("Enter")
    pg.wait_for_selector(".lp-kopf")
    assert pg.inner_text(".lp-kopf h1") == "Tastatur-Plan"
    assert not _quer(pg)

    # Abhaken, bleibt nach Neuladen
    assert pg.locator("[data-stueck]").count() > 0
    pg.locator("[data-stueck]").first.check()
    pg.wait_for_selector("section.lp-tag li.erledigt")
    pg.reload()
    pg.wait_for_selector(".lp-kopf")
    assert pg.locator("[data-stueck]:checked").count() >= 1
    assert not _quer(pg)

    # Liste mit Plan
    pg.goto(basis + "/#/lernplan")
    pg.wait_for_selector(".lp-plan")
    assert pg.locator(".lp-plan").count() == 1
    assert not _quer(pg)


def test_menuepunkt_je_schalter(tmp_path):
    pfad = _browser("light")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=pfad, args=["--no-sandbox"])
        try:
            for an in (True, False):
                with _server(tmp_path, an) as (basis, _):
                    pg = b.new_context(viewport={"width": 360, "height": 800}).new_page()
                    pg.set_default_timeout(10000)
                    fehler = []
                    pg.on("pageerror", lambda e: fehler.append(str(e)))
                    pg.on("console", lambda m: fehler.append(m.text) if m.type == "error" else None)
                    pg.goto(basis + "/")
                    pg.wait_for_selector("header.kopf nav")
                    pg.wait_for_load_state("networkidle")
                    assert (pg.locator("header.kopf nav a", has_text="Lernplan").count() == 1) is an
                    # ohne Modul führt die Lernplan-Route zurück zur Übersicht, ohne Fehlerseite
                    pg.goto(basis + "/#/lernplan")
                    pg.wait_for_load_state("networkidle")
                    assert (pg.locator("#lpNeu").count() == 1) is an
                    pg.close()
                    assert [f for f in fehler if "404" not in f] == []
        finally:
            b.close()
