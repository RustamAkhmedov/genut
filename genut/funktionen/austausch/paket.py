"""Importierbare Datei: gebaute Seite + Datenblock `genutQuelle` + Fußzeile (research.md R3, R6).

Die gebaute Seite wird nur gelesen; die Datei entsteht erst beim Herunterladen.
"""
from __future__ import annotations

import json
import re

from ...bilder import ausschnitt_base64
from ...projekt import Projekt
from .schema import FORMAT, bild_bloecke

AUS_DOKUMENT = re.compile(r"-b\d+\.jpg$")  # aus einem Dokument gelöstes Bild

FUSSZEILE = (
    '<footer class="genut-austausch"><style>'
    ".genut-austausch{margin:32px auto 0;padding:16px;max-width:40rem;text-align:center;"
    "font:13px/1.5 var(--sans,system-ui,sans-serif);color:var(--muted,#6f6f6f);"
    "border-top:1px solid var(--border,#ccc)}"
    ".genut-austausch a{color:var(--accent,#a8482a)}"
    "</style>Diese Datei kann in genut als Projekt importiert werden. "
    '<a href="https://github.com/RustamAkhmedov/genut">genut auf GitHub</a></footer>'
)


def paket_bauen(p: Projekt) -> dict:
    """Paket aus `projekt.json` und dem aktuellen Inhalt (data-model.md „Paket“)."""
    m, doc = p.meta(), p.inhalt()
    bilder = {}
    for b in bild_bloecke(doc):
        pfad = p.fotos / b.foto
        bilder[b.id] = {"art": "datei" if AUS_DOKUMENT.search(b.foto) else "foto",
                        "daten": ausschnitt_base64(pfad, b.bbox) if pfad.is_file() else ""}
    return {
        "art": "genut-projekt",
        "format": FORMAT,
        "projekt": {"name": m.name[:200], "fach": m.fach, "einstellungen": m.einstellungen.model_dump(mode="json")},
        "inhalt": doc.model_dump(mode="json"),
        "bilder": bilder,
    }


def einbetten(html: str, paket: dict) -> str:
    """Setzt Datenblock und Fußzeile vor das letzte </body> (fehlt es: ans Ende)."""
    # Ohne jedes "<" kann kein Inhalt den Block beenden (</script>, <!--)
    daten = json.dumps(paket, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    zusatz = f'<script type="application/json" id="genutQuelle">{daten}</script>\n{FUSSZEILE}\n'
    stellen = [t.start() for t in re.finditer("</body>", html, re.IGNORECASE)]
    i = stellen[-1] if stellen else len(html)
    return html[:i] + zusatz + html[i:]


def importierbar(p: Projekt) -> str:
    """Die gebaute Seite als importierbare Datei."""
    # read_bytes statt read_text: Zeilenenden bleiben, wie sie sind
    return einbetten(p.ausgabe.read_bytes().decode("utf-8"), paket_bauen(p))
