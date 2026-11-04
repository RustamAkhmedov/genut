"""Patches der KI anwenden, IDs vergeben, Elemente ersetzen/löschen."""
from __future__ import annotations

import secrets

from .schema import Aufgabe, Dokument, Frage, Karte, NeueAufgabe, NeueKarte, Patch, Thema


def neue_id(praefix: str, vergeben: set[str]) -> str:
    while True:
        i = f"{praefix}-{secrets.token_hex(4)}"
        if i not in vergeben:
            vergeben.add(i)
            return i


def alle_ids(doc: Dokument) -> set[str]:
    ids: set[str] = set()
    for t in doc.themen:
        ids.add(t.id)
        ids.update(b.id for b in t.bloecke)
    for a in doc.aufgaben:
        ids.add(a.id)
        ids.update(b.id for s in a.schritte for b in s.bloecke)
    ids.update(k.id for k in doc.karten)
    ids.update(q.id for q in doc.quiz)
    return ids


def _block_ids(bloecke, vergeben):
    for b in bloecke:
        b.id = neue_id("b", vergeben)
        b.pruefung = None
        b.gesperrt = False


def _aufgabe_ids(a: Aufgabe, vergeben):
    a.id = a.id or neue_id("a", vergeben)
    for s in a.schritte:
        _block_ids(s.bloecke, vergeben)


def patch_fehler(doc: Dokument, patch: Patch) -> list[str]:
    """Referenzfehler, die die KI korrigieren muss. Leere Liste = Patch ist anwendbar."""
    themen = {t.id for t in doc.themen}
    refs = [t.ref for t in patch.neue_themen]
    fehler = []
    if len(refs) != len(set(refs)):
        fehler.append("ref-Werte in neue_themen sind nicht eindeutig")
    gueltig = themen | set(refs)
    for nb in patch.neue_bloecke:
        if nb.thema_id not in themen:
            fehler.append(f"neue_bloecke: thema_id {nb.thema_id!r} gibt es nicht (bestehende: {sorted(themen)})")
    for a in patch.neue_aufgaben:
        if a.thema_ref not in gueltig:
            fehler.append(f"neue_aufgaben {a.titel!r}: thema_ref {a.thema_ref!r} unbekannt")
    for k in patch.neue_karten:
        if k.thema_ref not in gueltig:
            fehler.append(f"neue_karten: thema_ref {k.thema_ref!r} unbekannt")
    for q in patch.neue_fragen:
        if q.thema_ref not in gueltig:
            fehler.append(f"neue_fragen: thema_ref {q.thema_ref!r} unbekannt")
    return fehler


def patch_anwenden(doc: Dokument, patch: Patch) -> set[str]:
    """Wendet einen (vorher mit patch_fehler geprüften) Patch an. Gibt die IDs der neuen
    Elemente der obersten Ebene zurück (Blöcke in Themen, Aufgaben, Karten)."""
    vergeben = alle_ids(doc)
    neu: set[str] = set()
    if patch.projekt and not doc.themen:
        doc.projekt.titel = patch.projekt.titel or doc.projekt.titel
        doc.projekt.untertitel = patch.projekt.untertitel
    ref_zu_id = {t.id: t.id for t in doc.themen}
    for nt in patch.neue_themen:
        t = Thema(id=neue_id("t", vergeben), titel=nt.titel, kurz=nt.kurz, quelle=nt.quelle, bloecke=nt.bloecke)
        _block_ids(t.bloecke, vergeben)
        neu.update(b.id for b in t.bloecke)
        ref_zu_id[nt.ref] = t.id
        doc.themen.append(t)
    themen = {t.id: t for t in doc.themen}
    for nb in patch.neue_bloecke:
        t = themen[nb.thema_id]
        _block_ids([nb.block], vergeben)
        pos = next((i + 1 for i, b in enumerate(t.bloecke) if b.id == nb.nach_block_id), len(t.bloecke))
        t.bloecke.insert(pos, nb.block)
        neu.add(nb.block.id)
    for na in patch.neue_aufgaben:
        a = Aufgabe.model_validate(na.model_dump(exclude={"thema_ref"}))
        a.id = ""
        a.thema_id = ref_zu_id[na.thema_ref]
        if a.art == "probe":
            a.quelle = "ki"
        _aufgabe_ids(a, vergeben)
        doc.aufgaben.append(a)
        neu.add(a.id)
    for nk in patch.neue_karten:
        k = Karte.model_validate(nk.model_dump(exclude={"thema_ref"}))
        k.id = neue_id("k", vergeben)
        k.thema_id = ref_zu_id[nk.thema_ref]
        doc.karten.append(k)
        neu.add(k.id)
    for nq in patch.neue_fragen:
        q = Frage.model_validate(nq.model_dump(exclude={"thema_ref"}))
        q.id = neue_id("q", vergeben)
        q.thema_id = ref_zu_id[nq.thema_ref]
        doc.quiz.append(q)
        neu.add(q.id)
    return neu


# ---------------------------------------------------------------- Einzelne Elemente

def finden(doc: Dokument, id_: str):
    """Gibt (art, element, behälter_liste, thema) zurück; art in block|aufgabe|karte|frage|thema."""
    for t in doc.themen:
        if t.id == id_:
            return "thema", t, doc.themen, t
        for b in t.bloecke:
            if b.id == id_:
                return "block", b, t.bloecke, t
    for a in doc.aufgaben:
        if a.id == id_:
            return "aufgabe", a, doc.aufgaben, None
    for k in doc.karten:
        if k.id == id_:
            return "karte", k, doc.karten, None
    for q in doc.quiz:
        if q.id == id_:
            return "frage", q, doc.quiz, None
    raise KeyError(id_)


def ersetzen(doc: Dokument, id_: str, neu) -> None:
    """Ersetzt ein Element; ID, Thema-Zuordnung bleiben, Prüfstatus wird zurückgesetzt."""
    art, alt, liste, _ = finden(doc, id_)
    vergeben = alle_ids(doc)
    if art == "block":
        if neu.typ != alt.typ:
            raise ValueError(f"Typ darf sich nicht ändern ({alt.typ} → {neu.typ})")
        neu.id = id_
    elif art == "aufgabe":
        neu.id, neu.thema_id = id_, alt.thema_id
        for s in neu.schritte:
            _block_ids(s.bloecke, vergeben)
    elif art in ("karte", "frage"):
        neu.id, neu.thema_id = id_, alt.thema_id
    else:
        raise ValueError("Themen werden nicht ersetzt")
    neu.pruefung = None
    neu.gesperrt = False
    liste[liste.index(alt)] = neu


def loeschen(doc: Dokument, id_: str) -> None:
    art, el, liste, _ = finden(doc, id_)
    liste.remove(el)
    if art == "thema":
        doc.aufgaben = [a for a in doc.aufgaben if a.thema_id != id_]
        doc.karten = [k for k in doc.karten if k.thema_id != id_]
        doc.quiz = [q for q in doc.quiz if q.thema_id != id_]


def ids_vergeben(doc: Dokument) -> None:
    """Vergibt fehlende IDs (z. B. nach Bearbeitung im JSON-Editor)."""
    vergeben = alle_ids(doc) - {""}
    for t in doc.themen:
        t.id = t.id or neue_id("t", vergeben)
        for b in t.bloecke:
            b.id = b.id or neue_id("b", vergeben)
    for a in doc.aufgaben:
        a.id = a.id or neue_id("a", vergeben)
        for s in a.schritte:
            for b in s.bloecke:
                b.id = b.id or neue_id("b", vergeben)
    for k in doc.karten:
        k.id = k.id or neue_id("k", vergeben)
    for q in doc.quiz:
        q.id = q.id or neue_id("q", vergeben)


__all__ = ["patch_fehler", "patch_anwenden", "finden", "ersetzen", "loeschen", "ids_vergeben",
           "alle_ids", "NeueAufgabe", "NeueKarte"]
