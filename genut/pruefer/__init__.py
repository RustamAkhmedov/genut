"""Prüfer.

pruefe(doc, ids, fotos) prüft die Elemente der obersten Ebene (Blöcke in Themen,
Aufgaben, Karten) mit den angegebenen IDs, schreibt pruefung/gesperrt/ausdruck_js
direkt ins Dokument und gibt {id: Pruefung} zurück.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import ipaddress
import re

from ..schema import (Aufgabe, BildBlock, CheckEinheit, CheckGleich, CheckLoesungen, CheckNumerisch, CheckReaktion,
                      CheckSql, CheckSubnetz, Dokument, FormelBlock, Frage, GraphBlock, Karte, Pruefung, SqlErgebnis)
from ..faecher import profil
from . import tex as texmod
from .sandbox import ARBEITER, Zeitueberschreitung

# Felder mit Markdown/TeX je Blocktyp (Einzeltexte bzw. Listen von Texten)
MD_FELDER = ["md", "erklaerung_md", "titel", "beschriftung", "aufgabe_md", "anweisung_md", "text", "zweck_md",
             "beispiel_md", "inhalt_md", "begriff"]
MD_LISTEN = ["beispiele", "aufbau", "merkmale", "formulierungen", "motive"]
MERMAID_ARTEN = {"classDiagram", "erDiagram", "gantt", "flowchart", "graph", "sequenceDiagram", "mindmap",
                 "stateDiagram", "stateDiagram-v2", "pie", "timeline", "journey", "xychart-beta", "quadrantChart",
                 "block-beta", "gitGraph"}
LUECKE = re.compile(r"\[\[([^\[\]]*)\]\]")


def elemente(doc: Dokument) -> dict[str, object]:
    """Alle Elemente der obersten Ebene nach ID."""
    out: dict[str, object] = {}
    for t in doc.themen:
        for b in t.bloecke:
            out[b.id] = b
    for a in doc.aufgaben:
        out[a.id] = a
    for k in doc.karten:
        out[k.id] = k
    for q in doc.quiz:
        out[q.id] = q
    return out


def _bloecke_in(el) -> list:
    if isinstance(el, Aufgabe):
        return [b for s in el.schritte for b in s.bloecke]
    if isinstance(el, (Karte, Frage)):
        return []
    return [el]


def _tex_stellen(el) -> list[tuple[str, bool]]:
    stellen: list[tuple[str, bool]] = []
    texte: list[str | None] = []
    if isinstance(el, Aufgabe):
        texte += [el.titel, el.angabe_md, el.ergebnis.md] + [s.titel for s in el.schritte]
    elif isinstance(el, Karte):
        texte += [el.vorne_md, el.hinten_md]
    elif isinstance(el, Frage):
        texte += [el.frage_md, el.erklaerung_md] + list(el.optionen)
    for b in _bloecke_in(el):
        for f in MD_FELDER:
            texte.append(getattr(b, f, None))
        for f in MD_LISTEN:
            texte += getattr(b, f, None) or []
        if b.typ == "zeitleiste":
            texte += [x for e in b.eintraege for x in (e.titel, e.md)]
        if b.typ == "code":
            texte += [e.md for e in b.erklaerungen]
        if b.typ == "reaktion":
            stellen.append(("\\ce{" + b.gleichung + "}", True))
        if b.typ == "struktur":
            stellen += [("\\ce{" + f + "}", False) for f in (b.summenformel, b.halbstruktur) if f]
        if b.typ == "tabelle":
            texte += b.kopf + [z for zeile in b.zeilen for z in zeile]
        if isinstance(b, FormelBlock):
            stellen.append((b.tex, True))
            texte += [f"\\({v.name}\\) {v.bedeutung}" for v in b.variablen]
    for t in texte:
        stellen += texmod.aus_md(t)
    return stellen


def _dollar(el) -> list[str]:
    if any(b.typ in ("code", "befehl", "sql") for b in _bloecke_in(el)):
        return []  # dort ist $ legitim (Shell, Prompt, Template-Strings)
    roh = el.model_dump_json(exclude={"pruefung"})
    roh = re.sub(r"```.*?```", "", roh, flags=re.S)  # Codeblöcke in Markdown
    roh = re.sub(r"`[^`]*`", "", roh)                  # Inline-Code
    return ["TeX mit $ geschrieben – bitte \\( … \\) bzw. \\[ … \\] verwenden"] if "$" in roh else []


def _graphen(el) -> list:
    out = []
    for b in _bloecke_in(el):
        if isinstance(b, (FormelBlock, GraphBlock)) and b.graph is not None:
            out.append(b.graph)
    return out


def _check(c) -> tuple[bool | None, str]:
    """(True/False, meldung) oder (None, meldung) bei nicht prüfbar."""
    try:
        if isinstance(c, CheckGleich):
            return ARBEITER.ausfuehren("check_gleich", c.ausdruck, c.erwartet)
        if isinstance(c, CheckNumerisch):
            return ARBEITER.ausfuehren("check_numerisch", c.ausdruck, c.erwartet, c.toleranz)
        if isinstance(c, CheckLoesungen):
            return ARBEITER.ausfuehren("check_loesungen", c.gleichungen, c.variablen, c.erwartet)
        if isinstance(c, CheckEinheit):
            return ARBEITER.ausfuehren("check_einheit", c.ausdruck, c.erwartet, c.toleranz)
        if isinstance(c, CheckReaktion):
            return ARBEITER.ausfuehren("check_reaktion", c.gleichung)
        if isinstance(c, CheckSql):
            return ARBEITER.ausfuehren("check_sql", c.schema_sql, c.abfrage, c.erwartet, c.reihenfolge)
        if isinstance(c, CheckSubnetz):
            return ARBEITER.ausfuehren("check_subnetz", c.netz, c.erwartet.model_dump(exclude_none=True))
    except Zeitueberschreitung:
        return None, "Zeitüberschreitung beim Nachrechnen (10 s)"
    except RuntimeError as e:
        return False, f"check nicht auswertbar: {e}"
    return None, "unbekannte Check-Art"


def _frage_pruefen(q: Frage) -> list[str]:
    if q.art == "mc":
        f = []
        if len(q.optionen) != 4:
            f.append(f"Quizfrage (mc) braucht genau 4 optionen, hat {len(q.optionen)}")
        if q.richtig is None or not 0 <= q.richtig < max(1, len(q.optionen)):
            f.append("Quizfrage (mc): richtig muss der Index (0–3) der richtigen Option sein")
        if len({o.strip() for o in q.optionen}) != len(q.optionen):
            f.append("Quizfrage (mc): optionen sind nicht verschieden")
        return f
    f = []
    if q.wahr is None:
        f.append("Quizfrage (wahrfalsch): wahr muss true oder false sein")
    if q.optionen:
        f.append("Quizfrage (wahrfalsch): optionen muss leer sein")
    return f


def _block_pruefen(b) -> tuple[list[str], bool]:
    """Typspezifische Prüfung eines Blocks: (fehler, geprüft)."""
    t = b.typ
    if t == "reaktion" and b.ausgleichen:
        ok, m = _check(CheckReaktion(art="reaktion", gleichung=b.gleichung))
        return ([] if ok else [m]), bool(ok)
    if t == "struktur":
        try:
            ok, m = ARBEITER.ausfuehren("check_struktur", b.smiles, b.summenformel, b.halbstruktur)
        except Zeitueberschreitung:
            return ["Strukturformel: Zeitüberschreitung beim Prüfen"], False
        except RuntimeError as e:
            return [f"Strukturformel: {e}"], False
        return ([] if ok else [m]), bool(ok)
    if t == "sql":
        try:
            r = ARBEITER.ausfuehren("sql_ausfuehren", b.schema_sql, b.abfrage)
        except Zeitueberschreitung:
            r = {"spalten": [], "zeilen": [], "fehler": "Zeitüberschreitung (10 s) beim Ausführen"}
        b.ergebnis = SqlErgebnis(**r)
        return ([f"SQL-Block: {r['fehler']}"] if r["fehler"] else []), not r["fehler"]
    if t == "subnetzrechner":
        try:
            ipaddress.ip_interface(b.start.strip())
        except ValueError:
            return [f"subnetzrechner: start {b.start!r} ist keine Adresse mit Präfix (z. B. 192.168.1.10/24)"], False
    if t == "lueckentext":
        luecken = LUECKE.findall(b.text)
        if not luecken:
            return ["Lückentext ohne Lücken – jede Lücke als [[Lösung]] schreiben"], False
        if any(not x.strip() or not all(a.strip() for a in x.split("|")) for x in luecken):
            return ["Lückentext: leere Lücke oder leere Alternative in [[…]]"], False
    if t == "klimadiagramm":
        f = []
        if len(b.temperatur) != 12 or len(b.niederschlag) != 12:
            f.append(f"Klimadiagramm {b.ort}: je 12 Monatswerte nötig "
                     f"(Temperatur {len(b.temperatur)}, Niederschlag {len(b.niederschlag)})")
        if any(not -70 <= x <= 50 for x in b.temperatur):
            f.append(f"Klimadiagramm {b.ort}: Temperatur außerhalb −70…50 °C")
        if any(not 0 <= x <= 3000 for x in b.niederschlag):
            f.append(f"Klimadiagramm {b.ort}: Niederschlag außerhalb 0…3000 mm")
        return f, False
    if t == "zeitleiste" and len(b.eintraege) < 2:
        return ["Zeitleiste braucht mindestens 2 Einträge"], False
    if t == "textsorte" and not b.aufbau:
        return [f"Textsorte {b.name}: aufbau fehlt"], False
    if t == "diagramm":
        art = (b.mermaid.strip().split() or [""])[0]
        if art not in MERMAID_ARTEN:
            return [f"Diagramm: unbekannte Mermaid-Diagrammart {art!r} (erlaubt: {', '.join(sorted(MERMAID_ARTEN))})"], False
    return [], False


def pruefe(doc: Dokument, ids: set[str], fotos: Path | None = None, runde: int = 0) -> dict[str, Pruefung]:
    alle = elemente(doc)
    ziel = {i: alle[i] for i in ids if i in alle}
    zeit = datetime.now().isoformat(timespec="seconds")

    # TeX gesammelt in einem Node-Aufruf
    eintraege = [{"id": i, "tex": t, "display": d} for i, el in ziel.items() for t, d in _tex_stellen(el)]
    tex_fehler = texmod.pruefen(eintraege)

    ergebnis: dict[str, Pruefung] = {}
    pruefbar = bool(profil(doc.projekt.fach).checks)
    for i, el in ziel.items():
        fehler = list(tex_fehler.get(i, [])) + _dollar(el)
        geprueft = False
        offen: list[str] = []

        for g in _graphen(el):
            try:
                gf, js = ARBEITER.ausfuehren("graph_pruefen", g.model_dump())
            except Zeitueberschreitung:
                gf, js = ["Graph: Zeitüberschreitung beim Auswerten"], [None] * len(g.funktionen)
            for f, j in zip(g.funktionen, js):
                f.ausdruck_js = j
            fehler += gf
            geprueft = True

        for b in _bloecke_in(el):
            bf, bg = _block_pruefen(b)
            fehler += bf
            geprueft = geprueft or bg
            if isinstance(b, BildBlock):
                x, y, w, h = (b.bbox + [0, 0, 0, 0])[:4]
                if len(b.bbox) != 4 or x < 0 or y < 0 or x + w > 1.0001 or y + h > 1.0001 or w < 0.03 or h < 0.03:
                    fehler.append(f"bbox {b.bbox} ungültig (4 Werte, 0–1, Breite/Höhe ≥ 0.03)")
                if fotos is not None and not (fotos / b.foto).exists():
                    fehler.append(f"Foto {b.foto} existiert nicht")

        if isinstance(el, Frage):
            fehler += _frage_pruefen(el)
            if el.check is not None:
                ok, meldung = _check(el.check)
                if ok is None:
                    offen.append(meldung)
                elif ok:
                    geprueft = True
                else:
                    fehler.append(f"Rechenfrage: {meldung}")

        if isinstance(el, Aufgabe):
            c = el.ergebnis.check
            if c is None:
                if pruefbar and el.rechenaufgabe:  # nur Rechenaufgaben in Fächern mit Prüfarten brauchen einen check
                    offen.append("kein check angegeben – Ergebnis nicht maschinell geprüft")
            else:
                ok, meldung = _check(c)
                if ok is None:
                    offen.append(meldung)
                elif ok:
                    geprueft = True
                else:
                    fehler.append(f"Ergebnis falsch: {meldung}")

        if fehler:
            status = "fehler"
        elif offen:
            status = "nicht_pruefbar"
        elif geprueft:
            status = "ok"
        else:
            status = "ungeprueft"
        p = Pruefung(status=status, meldungen=fehler + offen, runden=runde, zeit=zeit)
        el.pruefung = p
        if status == "ok":
            el.gesperrt = True
        ergebnis[i] = p
    return ergebnis
