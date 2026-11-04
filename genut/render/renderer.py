"""inhalt.json → eine eigenständige Offline-HTML-Datei. Keine KI."""
from __future__ import annotations

import base64
import html
import json
import re
import subprocess
import tempfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markdown_it import MarkdownIt
from markupsafe import Markup

from .. import faecher
from ..bilder import ausschnitt_base64
from ..config import WURZEL
from ..schema import Dokument, FormelBlock, GraphBlock, SqlErgebnis

HIER = Path(__file__).resolve().parent
ASSETS = HIER / "assets"
GROESSE_WARNUNG = 3 * 1024 * 1024

_md = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False}).enable("table")
_TEX = re.compile(r"\\\(.+?\\\)|\\\[.+?\\\]", re.S)


def md(text: str | None, inline: bool = False) -> Markup:
    """Markdown → HTML; TeX-Stellen werden vorher geschützt, damit Markdown sie nicht zerlegt."""
    if not text:
        return Markup("")
    stellen: list[str] = []

    def weg(m):
        stellen.append(m.group(0))
        return f"GENUTTEX{len(stellen) - 1}XETTUNEG"

    roh = _TEX.sub(weg, text)
    out = _md.renderInline(roh) if inline else _md.render(roh)
    out = re.sub(r"GENUTTEX(\d+)XETTUNEG", lambda m: html.escape(stellen[int(m.group(1))], quote=False), out)
    return Markup(out)


_LUECKE = re.compile(r"\[\[([^\[\]]*)\]\]")


def luecken(text: str | None) -> Markup:
    """Lückentext: [[Lösung|Alternative]] → Eingabefeld; die Lösungen stehen im data-Attribut."""
    if not text:
        return Markup("")
    loes: list[list[str]] = []

    def weg(m):
        loes.append([x.strip() for x in m.group(1).split("|")])
        return f"GENUTLUECKE{len(loes) - 1}X"

    out = str(md(_LUECKE.sub(weg, text)))

    def ein(m):
        i = int(m.group(1))
        breite = max(4, max(len(x) for x in loes[i]) + 1)
        return (f'<input class="lk" type="text" size="{breite}" autocomplete="off" autocapitalize="off" '
                f'spellcheck="false" aria-label="Lücke {i + 1}" data-loesung="{html.escape(json.dumps(loes[i], ensure_ascii=False))}">')

    return Markup(re.sub(r"GENUTLUECKE(\d+)X", ein, out))


MONATE = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]


def _zahl(v: float) -> str:
    return (f"{v:.1f}".rstrip("0").rstrip(".") if v % 1 else f"{v:.0f}").replace(".", ",")


def klima(b) -> dict:
    """Klimadiagramm nach Walter/Lieth als SVG: 10 °C entsprechen 20 mm, 0 °C und 0 mm auf einer Linie.
    x-Koordinaten in Prozent, y in Pixeln: Das Diagramm wird nur breiter, die Schrift bleibt lesbar."""
    T = (list(b.temperatur) + [0.0] * 12)[:12]
    N = (list(b.niederschlag) + [0.0] * 12)[:12]
    H, O, U, XL, XR = 260, 24, 24, 11.0, 89.0
    tmin = min(0, int((min(T) // 10) * 10))
    nmax = max(max(N), 2 * max(max(T), 10))
    tmax = max(10, -(-nmax // 20) * 10)            # aufrunden auf 10 °C, Niederschlagsachse = 2 × Temperatur
    ih = H - O - U
    Y = lambda t: O + (tmax - t) / (tmax - tmin) * ih  # noqa: E731
    X = lambda i: XL + (i + 0.5) * (XR - XL) / 12      # noqa: E731
    T_FARBE, N_FARBE = "var(--err)", "var(--plot-2)"
    teile = [f'<svg width="100%" height="{H}" role="img" aria-label="Klimadiagramm {html.escape(b.ort)}: '
             f'Temperatur und Niederschlag je Monat" style="font-family:var(--sans);font-size:12px">']
    for t in range(tmin, int(tmax) + 1, 10):
        y = Y(t)
        teile.append(f'<line x1="{XL}%" x2="{XR}%" y1="{y:.1f}" y2="{y:.1f}" style="stroke:var(--plot-grid)" '
                     f'stroke-width="{1.5 if t == 0 else 1}"/>')
        teile.append(f'<text x="{XL - 1.5}%" y="{y + 4:.1f}" text-anchor="end" style="fill:{T_FARBE}">{t}</text>')
        if t >= 0:
            teile.append(f'<text x="{XR + 1.5}%" y="{y + 4:.1f}" style="fill:{N_FARBE}">{2 * t}</text>')
    teile.append(f'<text x="{XL - 1.5}%" y="11" text-anchor="end" font-weight="600" style="fill:{T_FARBE}">°C</text>')
    teile.append(f'<text x="{XR + 1.5}%" y="11" font-weight="600" style="fill:{N_FARBE}">mm</text>')
    bw = (XR - XL) / 12 * 0.62
    for i, n in enumerate(N):
        y0, y1 = Y(0), Y(n / 2)
        teile.append(f'<rect x="{X(i) - bw / 2:.2f}%" y="{y1:.1f}" width="{bw:.2f}%" height="{max(0, y0 - y1):.1f}" '
                     f'rx="2" fill-opacity=".75" style="fill:{N_FARBE}"><title>{MONATE[i]}: {_zahl(n)} mm</title></rect>')
    for i in range(11):
        teile.append(f'<line x1="{X(i):.2f}%" y1="{Y(T[i]):.1f}" x2="{X(i + 1):.2f}%" y2="{Y(T[i + 1]):.1f}" '
                     f'stroke-width="2.5" stroke-linecap="round" style="stroke:{T_FARBE}"/>')
    for i, t in enumerate(T):
        teile.append(f'<circle cx="{X(i):.2f}%" cy="{Y(t):.1f}" r="3.5" style="fill:{T_FARBE}"><title>{MONATE[i]}: {_zahl(t)} °C</title></circle>')
    for i, m in enumerate(MONATE):
        teile.append(f'<text x="{X(i):.2f}%" y="{H - 7}" text-anchor="middle" style="fill:var(--muted)">{m}</text>')
    teile.append("</svg>")
    return {"svg": Markup("".join(teile)), "mittel": _zahl(round(sum(T) / 12, 1)), "summe": _zahl(round(sum(N))),
            "monate": ["Jän", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"], "fmt": _zahl}


def sql_tabelle(e: SqlErgebnis | None) -> Markup:
    if e is None:
        return Markup("")
    if e.fehler:
        return Markup(f'<div class="sql-err">{html.escape(e.fehler)}</div>')
    if not e.spalten:
        return Markup('<p class="sql-status">Anweisung ausgeführt (kein Ergebnis).</p>')
    kopf = "".join(f"<th>{html.escape(str(s))}</th>" for s in e.spalten)
    zeilen = "".join("<tr>" + "".join(f"<td>{'NULL' if v is None else html.escape(str(v))}</td>" for v in z) + "</tr>"
                     for z in e.zeilen)
    return Markup(f'<div class="tbl-wrap" tabindex="0"><table><thead><tr>{kopf}</tr></thead><tbody>{zeilen}</tbody></table></div>')


def _svg_mindestbreite(svg: str) -> str:
    """Breite Diagramme nicht unter 65 % ihrer natürlichen Breite stauchen – lieber im Container scrollen."""
    m = re.search(r'viewBox="[-\d.]+ [-\d.]+ ([\d.]+) [\d.]+"', svg[:2000])
    if not m:
        return svg
    minw = round(float(m.group(1)) * 0.65)
    if 'style="' in svg[:svg.find(">")]:
        return svg.replace('style="', f'style="min-width:{minw}px;', 1)
    return svg.replace("<svg", f'<svg style="min-width:{minw}px"', 1)


def diagramm_hash(mermaid: str) -> str:
    import hashlib
    return hashlib.sha256(mermaid.strip().encode()).hexdigest()[:16]


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(HIER / "templates"), autoescape=select_autoescape(["j2", "html"]),
                      trim_blocks=True, lstrip_blocks=True)
    env.filters["md"] = md
    env.filters["mdi"] = lambda t: md(t, inline=True)
    env.filters["tex"] = lambda t: Markup(html.escape(t or "", quote=False))  # Markup: sonst escaped Jinja ein 2. Mal
    env.filters["luecken"] = luecken
    from .struktur import struktur
    env.globals.update(klima=klima, sql_tabelle=sql_tabelle, struktur=struktur)
    env.tests["match"] = lambda wert, muster: re.match(muster, wert or "") is not None
    return env


def _graphen(doc: Dokument) -> dict[str, dict]:
    """Alle Graphen nach Block-ID; nur mit von SymPy erzeugtem JS (ausdruck_js)."""
    out = {}
    bloecke = [b for t in doc.themen for b in t.bloecke]
    bloecke += [b for a in doc.aufgaben for s in a.schritte for b in s.bloecke]
    for b in bloecke:
        if isinstance(b, (FormelBlock, GraphBlock)) and b.graph is not None:
            g = b.graph
            if not g.funktionen or any(f.ausdruck_js is None for f in g.funktionen):
                continue
            out[b.id] = {
                "x": [g.x_min, g.x_max], "y": [g.y_min, g.y_max],
                "f": [{"js": f.ausdruck_js, "label": f.label} for f in g.funktionen],
                "p": [p.model_dump() for p in g.parameter],
                "fl": g.flaeche.model_dump() if g.flaeche else None,
            }
    return out


def _font_css() -> str:
    f = ASSETS / "fonts" / "source-serif-4-latin-600-normal.woff2"
    if not f.exists():
        return ""
    b64 = base64.b64encode(f.read_bytes()).decode()
    return ("@font-face{font-family:'Source Serif 4';font-style:normal;font-weight:600;font-display:swap;"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2')}}")


def _sqljs() -> str:
    """sql.js (SQLite als WebAssembly) für das SQL-Übungsfeld; nur eingebettet, wenn die Seite SQL-Blöcke hat."""
    d = WURZEL / "node_modules" / "sql.js" / "dist"
    js, wasm = d / "sql-wasm.js", d / "sql-wasm.wasm"
    if not js.exists() or not wasm.exists():
        return ""
    return (js.read_text().replace("</script", "<\\/script") +
            f"\nwindow.GENUT_SQL_WASM='{base64.b64encode(wasm.read_bytes()).decode()}';")


def html_bauen(doc: Dokument, fotos: Path | None, slug: str, diagramme: Path | None = None) -> str:
    """Rendert das HTML mit TeX-Quelltext (noch ohne MathJax)."""
    themen = {t.id: t for t in doc.themen}
    bilder = {}

    def diagramm(b) -> dict:
        h = diagramm_hash(b.mermaid)
        out = {"hash": h, "hell": None, "dunkel": None, "fehler": None}
        if diagramme is not None:
            for art in ("hell", "dunkel"):
                f = diagramme / f"{h}-{art}.svg"
                if f.exists():
                    out[art] = Markup(_svg_mindestbreite(f.read_text()))
            if (diagramme / f"{h}.fehler").exists():
                out["fehler"] = (diagramme / f"{h}.fehler").read_text()
        return out

    def bild(b):
        if b.id not in bilder:
            pfad = (fotos / b.foto) if fotos else None
            bilder[b.id] = ausschnitt_base64(pfad, b.bbox) if pfad and pfad.exists() else ""
        return bilder[b.id]

    spick = [(t, [b for b in t.bloecke if b.spick]) for t in doc.themen]
    spick = [(t, bl) for t, bl in spick if bl]
    graphen = _graphen(doc)
    # Vokabeln werden automatisch zu Karteikarten (ohne KI)
    vokabeln = [(t, b) for t in doc.themen for b in t.bloecke if b.typ == "vokabel"]
    alle_bloecke = [b for t in doc.themen for b in t.bloecke] + [b for a in doc.aufgaben for s in a.schritte for b in s.bloecke]
    hat_sql = any(b.typ == "sql" for b in alle_bloecke)
    daten = {
        "slug": slug,
        "graphen": graphen,
        "themen": [t.id for t in doc.themen],
        "aufgaben": [a.id for a in doc.aufgaben],
        "karten": [k.id for k in doc.karten] + [f"v-{b.id}" for _, b in vokabeln],
        "quiz": [q.id for q in doc.quiz],
    }
    fach = faecher.fach(doc.projekt.fach)
    # Strukturell kaputte Quizfragen (nicht beantwortbar) erscheinen nicht – wie kaputte Graphen
    quiz = [q for q in doc.quiz if (q.art == "mc" and len(q.optionen) >= 2 and q.richtig is not None
                                    and 0 <= q.richtig < len(q.optionen)) or (q.art == "wahrfalsch" and q.wahr is not None)]
    daten["quiz"] = [q.id for q in quiz]
    daten_json = json.dumps(daten, ensure_ascii=False).replace("</", "<\\/")
    return _env().get_template("seite.html.j2").render(
        doc=doc, p=doc.projekt, themen=doc.themen, thema=themen, aufgaben=doc.aufgaben, karten=doc.karten,
        spick=spick, graphen=graphen, bild=bild, daten_json=Markup(daten_json), quiz=quiz, vokabeln=vokabeln,
        fach=fach, diagramm=diagramm, sqljs=Markup(_sqljs()) if hat_sql else "",
        css=Markup((ASSETS / "seite.css").read_text()), font_css=Markup(_font_css()),
        js=Markup((ASSETS / "seite.js").read_text()),
    )


def rendern(doc: Dokument, fotos: Path | None, slug: str, ziel: Path, diagramme: Path | None = None) -> dict:
    roh = html_bauen(doc, fotos, slug, diagramme)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, dir=ziel.parent) as f:
        f.write(roh)
        tmp = Path(f.name)
    try:
        r = subprocess.run(["node", str(WURZEL / "node" / "prerender.js"), str(tmp), str(ziel)],
                           capture_output=True, text=True, cwd=WURZEL, timeout=300)
    finally:
        tmp.unlink(missing_ok=True)
    if r.returncode != 0:
        raise RuntimeError(f"prerender.js fehlgeschlagen: {r.stderr[-1500:]}")
    groesse = ziel.stat().st_size
    return {"datei": str(ziel), "bytes": groesse, "warnung": groesse > GROESSE_WARNUNG, "log": r.stdout.strip()}
