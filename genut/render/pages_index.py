"""Übersichtsseite für das GitHub-Pages-Repo, im selben Design wie die Lernseiten."""
from __future__ import annotations

import html
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"
FACH = {"mathe": "Mathematik", "netzwerk": "Netzwerktechnik", "englisch": "Englisch", "deutsch": "Deutsch"}


def index_html(seiten: list[dict]) -> str:
    css = (ASSETS / "seite.css").read_text()
    kacheln = []
    for s in seiten:
        e = html.escape
        datum = s.get("aktualisiert", "")[:10]
        kacheln.append(
            f'<a class="tile" href="{e(s["slug"])}/"><span class="tile-b"><b>{e(s.get("titel", s["slug"]))}</b>'
            f'<span>{e(FACH.get(s.get("fach", ""), "Lernseite"))}'
            f'{" · " + e(s["untertitel"]) if s.get("untertitel") else ""} · aktualisiert {e(datum)}</span></span></a>')
    liste = "\n".join(kacheln) or '<p class="leer">Noch keine Seiten.</p>'
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lernseiten</title><style>{css}</style></head>
<body style="padding-bottom:40px"><main>
<div class="hero"><div class="eyebrow">Übersicht</div><h1>Lernseiten</h1>
<p class="lead">Aus Heftfotos gebaut – zum Lernen am Handy oder Laptop.</p></div>
<div class="tiles">{liste}</div>
</main></body></html>
"""
