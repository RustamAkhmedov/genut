"""Klickt eine gerenderte Lernseite bei 375 px und 1280 px, hell und dunkel, durch.

Prüft: keine horizontale Scrollbar, keine Konsolenfehler, Graphen zeichnen, Schieberegler
ändern den Graphen, Aufdecken/Karten/Fortschritt funktionieren und überleben ein Neuladen.
Netzwerk ist blockiert (Offline-Test). Aufruf: python tests/shot.py <seite.html> [bilder-ordner]
Exit-Code 1 bei Fehlern.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def browser_pfad() -> str | None:
    for p in (os.environ.get("GENUT_CHROME"), "/opt/google/chrome/chrome", shutil.which("chromium"),
              shutil.which("google-chrome-stable"), shutil.which("chromium-browser")):
        if p and Path(p).exists():
            return p
    return None


# Lage jeder Kurve im Canvas: pro Pixelspalte die mittlere Zeile der Pixel in der Farbe --plot-1..4
# (-1 = Kurve nicht in dieser Spalte). Achsenbeschriftung und Gitter zählen bewusst nicht mit:
# Ein Regler, der nur die Skala ändert, die Kurve aber an derselben Stelle lässt, gilt als kaputt.
KURVE_JS = """(plot) => {
  const cv = plot.querySelector('canvas');
  const s = getComputedStyle(document.documentElement);
  const rgb = (n) => { const v = parseInt(s.getPropertyValue(n).trim().slice(1), 16); return [v >> 16 & 255, v >> 8 & 255, v & 255]; };
  const w = cv.width, h = cv.height, d = cv.getContext('2d').getImageData(0, 0, w, h).data;
  return [1, 2, 3, 4].map(k => {
    const [r, g, b] = rgb('--plot-' + k), spalten = [];
    for (let x = 0; x < w; x++) {
      let sum = 0, n = 0;
      for (let y = 0; y < h; y++) {
        const i = (y * w + x) * 4;
        if (Math.abs(d[i] - r) < 20 && Math.abs(d[i + 1] - g) < 20 && Math.abs(d[i + 2] - b) < 20) { sum += y; n++; }
      }
      spalten.push(n ? sum / n : -1);
    }
    return spalten;
  });
}"""


def _kurve_bewegt(vorher: list[list[float]], nachher: list[list[float]]) -> bool:
    for a, b in zip(vorher, nachher):
        anders = sum(1 for p, q in zip(a, b) if (p < 0) != (q < 0) or (p >= 0 and abs(p - q) > 2))
        if anders >= 0.03 * len(a):
            return True
    return False


def regler_pruefen(pg, tag: str) -> list[str]:
    """Jeder Schieberegler jedes Graphen muss die Kurve sichtbar verschieben (nicht nur die Achse)."""
    fehler = []
    plots = pg.eval_on_selector_all(
        ".view:not([data-view=spick]) .plot[data-graph]",
        "els => els.filter(e => e.querySelector('input[type=range]')).map(e => [e.closest('.view').dataset.view, e.dataset.graph])")
    for view, gid in plots:
        pg.evaluate(f"location.hash = '{view}'")
        pg.wait_for_timeout(120)
        sel = f".view[data-view='{view}'] .plot[data-graph='{gid}']"
        if view == "aufgaben":
            pg.evaluate(f"""(() => {{ const p = document.querySelector("{sel}"); const d = p.closest('details'); if (d) d.open = true;
                p.closest('.steps') && p.closest('.steps').querySelectorAll(':scope > *').forEach(e => e.hidden = false); }})()""")
            pg.wait_for_timeout(120)
        plot = pg.query_selector(sel)
        plot.scroll_into_view_if_needed()
        start = plot.evaluate(KURVE_JS)
        if sum(1 for spalte in start for y in spalte if y >= 0) < 50:
            fehler.append(f"{tag} {gid}: Graph scheint leer")
            continue
        for name in plot.eval_on_selector_all("input[type=range]", "els => els.map(e => e.dataset.p)"):
            inp = plot.query_selector(f"input[data-p='{name}']")
            alt = inp.evaluate("e => e.value")
            inp.evaluate("e => { e.value = (e.value === e.max ? e.min : e.max); e.dispatchEvent(new Event('input', {bubbles: true})); }")
            if not _kurve_bewegt(start, plot.evaluate(KURVE_JS)):
                fehler.append(f"{tag} {gid}: Schieberegler {name} verschiebt die Kurve nicht (nur die Achse ändert sich)")
            inp.evaluate(f"e => {{ e.value = {alt!r}; e.dispatchEvent(new Event('input', {{bubbles: true}})); }}")
    return fehler


def _zu(pg, sel: str) -> str | None:
    """Wechselt in die Ansicht, die das erste Element zu sel enthält; gibt den View-Namen zurück."""
    v = pg.evaluate(f"(() => {{ const e = document.querySelector({sel!r}); const v = e && e.closest('.view'); return v ? v.dataset.view : null; }})()")
    if v:
        pg.evaluate(f"location.hash = '{v}'")
        pg.wait_for_timeout(150)
    return v


def interaktion_pruefen(pg, tag: str) -> list[str]:
    """Bedient Quiz, Lückentext, SQL-Feld, Subnetz-Rechner und Code-Erklärungen wie ein Schüler."""
    fehler = []
    # Quiz: richtige Antwort anklicken → Rückmeldung „Richtig“, falsche → „Leider falsch“ und Wiederholung
    if pg.query_selector("#quizBank .qz"):
        pg.evaluate("location.hash = 'quiz'")
        pg.wait_for_timeout(200)
        n = pg.eval_on_selector_all("#quizBank .qz", "e => e.length")
        for _ in range(n):
            q = pg.evaluate("""(() => { const k = document.querySelector('#quizKarte');
                const frage = k.querySelector('.qz-frage'); if (!frage) return null;
                const bank = Array.from(document.querySelectorAll('#quizBank .qz')).find(x => x.querySelector('.qf').innerHTML === frage.innerHTML);
                return bank ? {art: bank.dataset.art, richtig: bank.dataset.art === 'mc' ? bank.dataset.richtig : bank.dataset.wahr,
                               html: bank.dataset.art === 'mc' ? bank.querySelectorAll('.qo')[+bank.dataset.richtig].innerHTML : null} : null; })()""")
            if not q:
                fehler.append(f"{tag} quiz: Frage nicht gefunden")
                break
            if q["art"] == "mc":
                pg.evaluate("""(h) => Array.from(document.querySelectorAll('#quizKarte .qz-opt')).find(b => b.querySelector('.prose').innerHTML === h).click()""", q["html"])
            else:
                pg.click(f"#quizKarte .qz-opt[data-i='{q['richtig']}']")
            fb = pg.text_content("#quizKarte .qz-fb") or ""
            if "Richtig" not in fb:
                fehler.append(f"{tag} quiz: richtige Antwort nicht als richtig erkannt ({fb[:60]!r})")
            pg.click("#qzWeiter")
        if "Geschafft" not in (pg.text_content("#quizKarte") or ""):
            fehler.append(f"{tag} quiz: keine Auswertung am Ende")
    # Lückentext: Lösungen eintragen → „n von n richtig“
    if pg.query_selector("[data-lueckentext]") and _zu(pg, "[data-lueckentext] input.lk"):
        box = pg.query_selector(".view:not([hidden]) [data-lueckentext]:has(input.lk)")
        if box:
            felder = box.query_selector_all("input.lk")
            for f in felder:
                f.fill(f.evaluate("e => JSON.parse(e.dataset.loesung).slice(-1)[0]").upper())  # Alternative + Großschreibung
            box.query_selector("[data-lt-pruefen]").click()
            stand = box.query_selector(".lt-stand").text_content()
            if stand != f"{len(felder)} von {len(felder)} richtig":
                fehler.append(f"{tag} lückentext: {stand!r}")
    # SQL: Beispiel ausführen → Ergebnistabelle aus sql.js
    if pg.query_selector("[data-sql]") and _zu(pg, "[data-sql]"):
        box = pg.query_selector(".view:not([hidden]) [data-sql]")
        box.query_selector("[data-sql-run]").click()
        try:
            pg.wait_for_function("b => /Zeile|fertig|Fehler|nicht verfügbar/.test(b.querySelector('.sql-status').textContent)", arg=box, timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        st = box.query_selector(".sql-status").text_content()
        if "Zeile" not in st:
            fehler.append(f"{tag} sql: Ausführen fehlgeschlagen ({st!r})")
    # Subnetz-Rechner: Eingabe → Broadcast; IPv6 → Netzadresse
    if pg.query_selector("[data-subnetz]") and _zu(pg, "[data-subnetz]"):
        box = pg.query_selector(".view:not([hidden]) [data-subnetz]")
        inp = box.query_selector(".sn-in")
        inp.fill("10.1.2.3/20")
        if "10.1.15.255" not in box.text_content():
            fehler.append(f"{tag} subnetz: falscher Broadcast für 10.1.2.3/20")
        inp.fill("2001:db8:abcd:12::1/64")
        if "2001:db8:abcd:12::/64" not in box.text_content():
            fehler.append(f"{tag} subnetz: IPv6-Netz falsch")
        inp.fill("quatsch")
        if not box.query_selector(".sn-fehler").text_content():
            fehler.append(f"{tag} subnetz: keine Fehlermeldung bei ungültiger Eingabe")
    # Code-Erklärung: Klick hebt Zeilen hervor
    if pg.query_selector(".code-erkl li") and _zu(pg, ".code-erkl li"):
        li = pg.query_selector(".view:not([hidden]) .code-erkl li")
        li.click()
        if not pg.query_selector(".view:not([hidden]) .code .cl.hl"):
            fehler.append(f"{tag} code: Zeilen werden nicht hervorgehoben")
    return fehler


def pruefen(seite: Path, bilder: Path | None = None) -> list[str]:
    fehler: list[str] = []
    url = seite.resolve().as_uri()
    with sync_playwright() as p:
        pfad = browser_pfad()
        b = p.chromium.launch(executable_path=pfad, args=["--no-sandbox"]) if pfad else p.chromium.launch()
        for breite, hoehe in ((375, 800), (1280, 900)):
            for schema in ("light", "dark"):
                tag = f"{breite}px/{schema}"
                ktx = b.new_context(viewport={"width": breite, "height": hoehe}, color_scheme=schema, device_scale_factor=2)
                ktx.route("**/*", lambda r: r.continue_() if r.request.url.startswith("file:") else r.abort())
                pg = ktx.new_page()
                pg.on("console", lambda m, t=tag: fehler.append(f"{t} console.{m.type}: {m.text}") if m.type == "error" else None)
                pg.on("pageerror", lambda e, t=tag: fehler.append(f"{t} pageerror: {e}"))
                pg.goto(url)
                pg.wait_for_timeout(200)
                views = pg.eval_on_selector_all(".view", "els => els.map(e => e.dataset.view)")
                for v in views:
                    pg.evaluate(f"location.hash = '{v}'")
                    pg.wait_for_timeout(120)
                    if v == "aufgaben":
                        pg.evaluate("document.querySelectorAll('#aufgListe details').forEach(d => d.open = true)")
                        pg.evaluate("document.querySelectorAll('.steps-ctl .btn.ghost').forEach(b => { if (!b.hidden && b.textContent.startsWith('Alle')) b.click(); })")
                        pg.wait_for_timeout(150)
                    if v == "karten" and pg.query_selector("#flash"):
                        pg.click("#flash")
                        pg.wait_for_timeout(450)
                    ow = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                    if ow > 0:
                        fehler.append(f"{tag} {v}: horizontale Scrollbar ({ow}px)")
                    if bilder and (v in ("start", "aufgaben", "karten", "quiz", "spick") or v.startswith("thema-")):
                        bilder.mkdir(parents=True, exist_ok=True)
                        pg.screenshot(path=str(bilder / f"{breite}-{schema}-{v}.png"), full_page=True)
                # Graphen: gezeichnet und reagieren auf Schieberegler
                fehler += regler_pruefen(pg, tag)
                fehler += interaktion_pruefen(pg, tag)
                # Fortschritt überlebt Neuladen
                if breite == 375 and schema == "light":
                    t = pg.evaluate("JSON.parse(document.getElementById('genutDaten').textContent).themen[0]")
                    if t:
                        pg.evaluate(f"location.hash = 'thema-{t}'")
                        pg.click(f"[data-gelesen='{t}']")
                        pg.reload()
                        pg.wait_for_timeout(150)
                        txt = pg.text_content("#progressText")
                        if not txt or txt.strip() == "0 %":
                            fehler.append(f"{tag}: Fortschritt nach Neuladen verloren ({txt})")
                ktx.close()
        b.close()
    return fehler


if __name__ == "__main__":
    f = pruefen(Path(sys.argv[1]), Path(sys.argv[2]) if len(sys.argv) > 2 else None)
    print("Fehler:", len(f))
    for x in f:
        print(" ", x)
    sys.exit(1 if f else 0)
