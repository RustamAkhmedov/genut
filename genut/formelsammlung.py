"""Formelauswahl eines Projekts (projekte/<slug>/formelsammlung.json) und Formelliste aus inhalt.json."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from markdown_it import MarkdownIt
from pydantic import ValidationError

from .config import WURZEL, node_befehl
from .faecher import fach as fach_von
from .projekt import Projekt, atomar_schreiben
from .schema import Dokument, _M


class AuswahlEintrag(_M):
    block_id: str
    variablen: bool = True
    erklaerung: bool = False


class LetzteErzeugung(_M):
    zeit: str
    formeln: int
    seiten: int
    warnungen: list[str] = []


class FormelAuswahl(_M):
    schema_version: int = 1
    eintraege: list[AuswahlEintrag] = []
    letzte_erzeugung: LetzteErzeugung | None = None


class UnbekannteFormel(ValueError):
    """Kennung gehört zu keinem Formel-Block des Projekts."""


def _pfad(projekt: Projekt):
    return projekt.ordner / "formelsammlung.json"


def formeln(doc: Dokument) -> list[dict]:
    """Alle Formel-Blöcke in Projektreihenfolge (Themen, dann Blöcke)."""
    out = []
    for t in doc.themen:
        for b in t.bloecke:
            if b.typ != "formel":
                continue
            out.append({
                "id": b.id, "thema_id": t.id, "thema": t.titel, "titel": b.titel or "",
                "tex": b.tex, "variablen": [v.model_dump() for v in b.variablen],
                "erklaerung_md": b.erklaerung_md, "spick": b.spick,
                "pruefung": b.pruefung.status if b.pruefung else "ungeprueft",
            })
    return out


def _standard(doc: Dokument) -> list[AuswahlEintrag]:
    return [AuswahlEintrag(block_id=f["id"]) for f in formeln(doc) if f["spick"]]


def _auswahl_lesen(projekt: Projekt) -> FormelAuswahl | None:
    try:
        return FormelAuswahl.model_validate_json(_pfad(projekt).read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError):
        return None


def auswahl_laden(projekt: Projekt) -> FormelAuswahl:
    """Gespeicherte Auswahl; fehlende oder kaputte Datei → Standardauswahl (Spickzettel-Formeln)."""
    a = _auswahl_lesen(projekt)
    if a is None:
        return FormelAuswahl(eintraege=_standard(projekt.inhalt()))
    return a


def auswahl_speichern(projekt: Projekt, eintraege: list[AuswahlEintrag]) -> FormelAuswahl:
    """Prüft die Kennungen, fasst doppelte zusammen (der letzte gewinnt) und schreibt atomar."""
    gueltig = {f["id"] for f in formeln(projekt.inhalt())}
    neu: dict[str, AuswahlEintrag] = {}
    for e in eintraege:
        if e.block_id not in gueltig:
            raise UnbekannteFormel(e.block_id)
        neu[e.block_id] = e
    alt = _auswahl_lesen(projekt)
    a = FormelAuswahl(eintraege=list(neu.values()), letzte_erzeugung=alt.letzte_erzeugung if alt else None)
    atomar_schreiben(_pfad(projekt), a.model_dump_json(indent=2))
    return a


def aufloesen(projekt: Projekt) -> list[tuple[dict, AuswahlEintrag]]:
    """Gewählte Formeln samt Eintrag in Projektreihenfolge; gelöschte Blöcke entfallen, neue sind ungewählt."""
    gewaehlt = {e.block_id: e for e in auswahl_laden(projekt).eintraege}
    return [(f, gewaehlt[f["id"]]) for f in formeln(projekt.inhalt()) if f["id"] in gewaehlt]


class KeineFormelGewaehlt(ValueError):
    """Die Auswahl ist leer."""


class ErstellungLaeuft(RuntimeError):
    """Für dieses Projekt läuft schon eine Erstellung."""


class PdfFehler(RuntimeError):
    """Node oder der PDF-Bau ist gescheitert (Meldung im Text)."""


_sperren: dict[str, threading.Lock] = {}
_sperren_lock = threading.Lock()
ZEITLIMIT = 120


def _sperre(projekt: Projekt) -> threading.Lock:
    with _sperren_lock:
        return _sperren.setdefault(str(projekt.ordner), threading.Lock())


def pdf_pfad(projekt: Projekt) -> Path:
    return projekt.ordner / "out" / "formelsammlung.pdf"


def pdf_info(projekt: Projekt) -> dict | None:
    """Für die API: {vorhanden, zeit, formeln, seiten, warnungen} oder None, wenn nie erzeugt oder PDF fehlt."""
    le = auswahl_laden(projekt).letzte_erzeugung
    if le is None or not pdf_pfad(projekt).exists():
        return None
    return {"vorhanden": True, "zeit": le.zeit, "formeln": le.formeln, "seiten": le.seiten,
            "warnungen": list(le.warnungen)}


_md = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False}).enable("table")
# abgesetzt: \[…\] und $$…$$; im Text: \(…\) und $…$ (nicht an Leerraum grenzend, damit „5 $ und 6 $“ Text bleibt)
_TEX = re.compile(r"\\\[(.+?)\\\]|\$\$(.+?)\$\$|\\\((.+?)\\\)|\$(?=\S)([^$\n]*?\S)\$", re.S)
_STELLE = re.compile(r"\ue000(\d+)\ue001")


def _zusammenfassen(stuecke: list[dict]) -> list[dict]:
    out: list[dict] = []
    for st in stuecke:
        if not st["s"] and st["t"] != "formel":
            continue
        if out and out[-1]["t"] == st["t"] and st["t"] in ("text", "fett", "kursiv", "code"):
            out[-1]["s"] += st["s"]
        else:
            out.append(st)
    return out


def erklaerung_stuecke(md_text: str | None) -> list[list[dict]]:
    """Markdown des Erklärtexts → Absätze aus Textstücken {"t": text|fett|kursiv|code|formel|formel_block, "s": …}.

    Aufzählungspunkte sind eigene Absätze, deren erstes Stück zusätzlich "punkt": true trägt.
    Unbekanntes Markdown (Überschriften, Tabellen, Links, Bilder, HTML) wird zu einfachem Text."""
    if not md_text or not md_text.strip():
        return []
    stellen: list[tuple[str, str]] = []

    def weg(m):
        if m.group(1) is not None:
            stellen.append(("formel_block", m.group(1).strip()))
        elif m.group(2) is not None:
            stellen.append(("formel_block", m.group(2).strip()))
        else:
            stellen.append(("formel", (m.group(3) if m.group(3) is not None else m.group(4)).strip()))
        return f"\ue000{len(stellen) - 1}\ue001"

    def zurueck(text: str) -> str:
        def r(m):
            t, s = stellen[int(m.group(1))]
            return {"formel": f"\\({s}\\)", "formel_block": f"\\[{s}\\]"}[t]
        return _STELLE.sub(r, text)

    def teile(text: str, art: str) -> list[dict]:
        out, pos = [], 0
        for m in _STELLE.finditer(text):
            out.append({"t": art, "s": text[pos:m.start()]})
            t, s = stellen[int(m.group(1))]
            out.append({"t": t, "s": s})
            pos = m.end()
        out.append({"t": art, "s": text[pos:]})
        return out

    def inline(tok) -> list[dict]:
        out, fett, kursiv = [], 0, 0
        for c in tok.children or []:
            if c.type == "strong_open":
                fett += 1
            elif c.type == "strong_close":
                fett -= 1
            elif c.type == "em_open":
                kursiv += 1
            elif c.type == "em_close":
                kursiv -= 1
            elif c.type in ("softbreak", "hardbreak"):
                out.append({"t": "text", "s": " "})
            elif c.type == "code_inline":
                out.append({"t": "code", "s": zurueck(c.content)})
            elif c.type == "image":
                out.append({"t": "text", "s": zurueck(c.content)})
            elif c.type in ("text", "html_inline"):
                out.extend(teile(c.content, "fett" if fett > 0 else "kursiv" if kursiv > 0 else "text"))
        return _zusammenfassen(out)

    absaetze: list[list[dict]] = []
    punkt_offen = False  # nächster Absatz ist der erste eines Listenpunkts
    zeile: list[list[dict]] | None = None  # Zellen der aktuellen Tabellenzeile

    def neu(stuecke: list[dict]) -> None:
        nonlocal punkt_offen
        if not stuecke:
            return
        if punkt_offen:
            stuecke[0]["punkt"] = True
            punkt_offen = False
        absaetze.append(stuecke)

    for tok in _md.parse(_TEX.sub(weg, md_text)):
        if tok.type == "list_item_open":
            punkt_offen = True
        elif tok.type == "tr_open":
            zeile = []
        elif tok.type == "tr_close":
            stuecke: list[dict] = []
            for i, zelle in enumerate(zeile or []):
                if i:
                    stuecke.append({"t": "text", "s": " | "})
                stuecke.extend(zelle)
            neu(_zusammenfassen(stuecke))
            zeile = None
        elif tok.type == "inline":
            if zeile is not None:
                zeile.append(inline(tok))
            else:
                neu(inline(tok))
        elif tok.type in ("fence", "code_block", "html_block"):
            neu(_zusammenfassen(teile(tok.content.strip("\n"), "text")))
    return absaetze


def _warnung(x) -> str:
    """Meldung des PDF-Baus mit dem Namen der Formel (FR-011), wenn die Meldung ihn nicht schon nennt."""
    if not isinstance(x, dict):
        return str(x)
    meldung, titel = str(x.get("meldung", "")), str(x.get("titel", "")).strip()
    return meldung if not titel or titel in meldung else f"„{titel}“: {meldung}"


_KENNZEICHEN = {"fehler": "nicht bestätigt", "nicht_pruefbar": "ungeprüft"}


def _eingabe(projekt: Projekt, gewaehlt: list[tuple[dict, AuswahlEintrag]]) -> dict:
    themen: dict[str, dict] = {}
    for f, e in gewaehlt:  # Reihenfolge der Projekt-Themen bleibt erhalten
        t = themen.setdefault(f["thema_id"], {"titel": f["thema"], "formeln": []})
        t["formeln"].append({
            "id": f["id"], "titel": f["titel"], "tex": f["tex"],
            "kennzeichen": _KENNZEICHEN.get(f["pruefung"], ""),
            "variablen": [{"tex": v["name"], "text": v["bedeutung"]} for v in f["variablen"]] if e.variablen else [],
            "erklaerung": erklaerung_stuecke(f["erklaerung_md"]) if e.erklaerung else [],
        })
    meta = projekt.meta()
    return {"projekt": meta.name, "fach": fach_von(meta.fach).name,
            "datum": datetime.now().strftime("%d.%m.%Y"), "themen": list(themen.values())}


def erzeugen(projekt: Projekt, eintraege: list[AuswahlEintrag] | None = None) -> dict:
    """Baut out/formelsammlung.pdf; liefert {ok, formeln, seiten, warnungen, zeit}."""
    sperre = _sperre(projekt)
    if not sperre.acquire(blocking=False):
        raise ErstellungLaeuft(projekt.slug)
    try:
        if eintraege is not None:
            auswahl_speichern(projekt, eintraege)
        gewaehlt = aufloesen(projekt)
        if not gewaehlt:
            raise KeineFormelGewaehlt()
        ziel = pdf_pfad(projekt)
        ziel.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="formelsammlung-") as tmpdir:
            ein = Path(tmpdir) / "eingabe.json"
            aus = Path(tmpdir) / "formelsammlung.pdf"
            ein.write_text(json.dumps(_eingabe(projekt, gewaehlt), ensure_ascii=False), encoding="utf-8")
            try:
                r = subprocess.run([node_befehl(), str(WURZEL / "node" / "formelsammlung.js"), str(ein), str(aus)],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace",
                                   cwd=WURZEL, timeout=ZEITLIMIT)
            except subprocess.TimeoutExpired:
                raise PdfFehler(f"Zeitüberschreitung nach {ZEITLIMIT} s") from None
            except OSError as e:
                raise PdfFehler(f"Node nicht startbar: {e}") from e
            if r.returncode != 0:
                raise PdfFehler((r.stderr or r.stdout or "unbekannter Fehler").strip()[-1500:])
            try:
                erg = json.loads(r.stdout)
            except ValueError:
                raise PdfFehler("Ungültige Antwort von node/formelsammlung.js") from None
            if not isinstance(erg, dict) or not erg.get("ok"):
                raise PdfFehler(str((erg or {}).get("meldung") or "PDF-Bau fehlgeschlagen") if isinstance(erg, dict)
                                else "PDF-Bau fehlgeschlagen")
            if not aus.exists():
                raise PdfFehler("Node hat keine PDF-Datei geschrieben")
            if not erg.get("formeln"):
                gruende = "; ".join(str(f.get("meldung", "")) for f in erg.get("fehler") or [] if isinstance(f, dict))
                raise PdfFehler("Keine der gewählten Formeln ließ sich setzen" + (f": {gruende}" if gruende else "."))
            # gleiches Dateisystem wie das Ziel, damit os.replace atomar ist
            zwischen = ziel.with_name(ziel.name + ".tmp")
            try:
                with open(aus, "rb") as q, open(zwischen, "wb") as z:
                    z.write(q.read())
                os.replace(zwischen, ziel)
            finally:
                zwischen.unlink(missing_ok=True)
        warnungen = [_warnung(x) for x in erg.get("fehler") or []]
        zeit = datetime.now().isoformat(timespec="seconds")
        le = LetzteErzeugung(zeit=zeit, formeln=int(erg.get("formeln", len(gewaehlt))),
                             seiten=int(erg.get("seiten", 0)), warnungen=warnungen)
        a = auswahl_laden(projekt)
        a.letzte_erzeugung = le
        atomar_schreiben(_pfad(projekt), a.model_dump_json(indent=2))
        return {"ok": True, "formeln": le.formeln, "seiten": le.seiten, "warnungen": warnungen, "zeit": zeit}
    finally:
        sperre.release()
