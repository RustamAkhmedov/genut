"""Logik der mündlichen Prüfung (specs/005-muendliche-pruefung/research.md Punkte 3, 4, 5, 7, 11).

Teil 1 (T003): Material, Entschärfen, Note/Ergebnis, Speicherschicht.
Teil 2 (T007): Ablauf (starten, antworten, weiter, beenden, bewerten, zustand) unten als eigener Abschnitt.
"""
from __future__ import annotations

import re
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence

from pydantic import BaseModel, ValidationError

from ... import faecher
from ...config import projekte_ordner
from ...modelle.base import ModellFehler, waehlen  # waehlen wird in Tests per monkeypatch ersetzt
from ...projekt import Projekt, atomar_schreiben
from ...schema import Dokument, ki_schema
from .schema import (ANTWORT_MAX, ErgebnisLuecke, ErgebnisRueckmeldung, Nachricht, PlanFrageGespeichert,
                     Pruefung, PruefungsErgebnis, PruefungsPlan, Pruefungsbewertung, Pruefungszug, PunkteEintrag)

# ---------------------------------------------------------------- Material (research.md Punkt 4)

_OHNE_TEXT = {"bild", "graph", "subnetzrechner"}


def _s(x) -> str:
    return str(x).strip() if x not in (None, "") else ""


def _block_text(b) -> str:
    """Nützlicher Text eines Blocks (ohne Bilder und Graphen)."""
    t = b.typ
    if t in _OHNE_TEXT:
        return ""
    z: list[str] = []

    def add(*teile):
        z.extend(_s(p) for p in teile if _s(p))

    if t == "text":
        add(b.md)
    elif t == "definition":
        add(f"{b.begriff}: {b.md}")
    elif t == "regel":
        add(b.titel, b.md, *[f"Beispiel: {x}" for x in b.beispiele])
    elif t == "formel":
        add(b.titel, b.tex, b.erklaerung_md, *[f"{v.name}: {v.bedeutung}" for v in b.variablen])
    elif t == "tabelle":
        add(b.titel, " | ".join(b.kopf), *[" | ".join(map(str, r)) for r in b.zeilen])
    elif t == "hinweis":
        add(f"{'Tipp' if b.art == 'tipp' else 'Falle'}: {b.md}")
    elif t == "code":
        add(b.code, b.erklaerung_md, *[e.md for e in b.erklaerungen])
    elif t == "befehl":
        add(b.befehl, b.erklaerung_md, b.kontext)
    elif t == "vokabel":
        add(f"{b.wort} = {b.uebersetzung}", b.beispiel)
    elif t == "zeitleiste":
        add(b.titel, *[f"{e.zeit}: {e.titel} {_s(e.md)}" for e in b.eintraege])
    elif t == "werk":
        add(f"{b.titel} ({b.autor})", b.inhalt_md, *b.motive)
    else:  # übrige Typen: alle Textfelder der Reihe nach
        for name, wert in b:
            if name in ("id", "quelle", "foto", "spick", "gesperrt", "pruefung", "typ", "ergebnis"):
                continue
            if isinstance(wert, str):
                add(wert)
            elif isinstance(wert, list) and all(isinstance(x, str) for x in wert):
                add(*wert)
    return "\n".join(z)


def material_text(doc: Dokument, thema_ids: Sequence[str], grenze: int) -> str:
    """Stoff der gewählten Themen als Text: Titel, `kurz`, dann je Block der nützliche Text.

    Die Länge verteilt sich gleichmäßig auf die Themen (jedes Thema bleibt mit seinem Titel vertreten) und ist
    hart auf `grenze` Zeichen begrenzt. Unbekannte Themenkennungen werden übersprungen."""
    gewaehlt = [t for i in thema_ids for t in doc.themen if t.id == i]
    if not gewaehlt or grenze <= 0:
        return ""
    anteil = max(1, (grenze - 2 * (len(gewaehlt) - 1)) // len(gewaehlt))
    teile: list[str] = []
    for t in gewaehlt:
        zeilen = [f"## {t.titel}"] + ([t.kurz.strip()] if t.kurz.strip() else [])
        text = "\n".join(zeilen)
        for b in t.bloecke:
            if len(text) >= anteil:
                break
            bt = _block_text(b)
            if bt:
                text += "\n" + bt
        teile.append(text[:anteil])
    return "\n\n".join(teile)[:grenze]


# ---------------------------------------------------------------- Entschärfen (research.md Punkt 5)

_ENDMARKE = re.compile(r"</(\s*)(material|antwort|dialog)(\s*)>", re.IGNORECASE)


def entschaerfen(text: str) -> str:
    """Macht die Endmarken </material>, </antwort> und </dialog> unschädlich (`<\\/…>`)."""
    return _ENDMARKE.sub(lambda m: f"<\\/{m.group(1)}{m.group(2)}{m.group(3)}>", text or "")


# ---------------------------------------------------------------- Note und Ergebnis (research.md Punkt 11)

NOTEN = ((87.5, 1, "Sehr gut"), (75.0, 2, "Gut"), (62.5, 3, "Befriedigend"), (50.0, 4, "Genügend"))
NICHT_GENUEGEND = (5, "Nicht genügend")


def note(prozent: float) -> tuple[int, str]:
    """(Note 1 bis 5, Name) zu einem Prozentwert; Grenzen 87,5 / 75 / 62,5 / 50 gehören zur besseren Note."""
    for grenze, n, name in NOTEN:
        if prozent >= grenze:
            return n, name
    return NICHT_GENUEGEND


def ergebnis_rechnen(plan: Sequence[PlanFrageGespeichert], punkte: Sequence[PunkteEintrag],
                     verkuerzt: bool) -> PruefungsErgebnis:
    """Punkte, Prozent und Note aus den Bewertungen. Prozent = Punkte / (2 · beantwortete Fragen) · 100.
    Zählt nur, was zu einer Frage des Plans gehört. Ohne beantwortete Frage: keine Note."""
    nrs = {f.nr for f in plan}
    zaehlt = [p for p in punkte if p.nr in nrs]
    if not zaehlt:
        return PruefungsErgebnis(punkte=0, maximal=0, prozent=0.0, note=None, note_name=None,
                                 verkuerzt=verkuerzt, begruendung="Nichts zu bewerten.")
    summe = sum(p.punkte for p in zaehlt)
    maximal = 2 * len(zaehlt)
    prozent = summe / maximal * 100
    n, name = note(prozent)
    return PruefungsErgebnis(punkte=summe, maximal=maximal, prozent=round(prozent, 2), note=n,
                             note_name=name, verkuerzt=verkuerzt)


# ---------------------------------------------------------------- Speicherschicht (research.md Punkt 7)

_ID = re.compile(r"^pr-[0-9a-f]{8}$")
_SLUG = re.compile(r"^[a-z0-9-]+$")
_sperren: dict[str, threading.Lock] = {}
_sperren_wache = threading.Lock()


def _ordner(slug: str) -> Path:
    if not isinstance(slug, str) or not _SLUG.fullmatch(slug):
        raise ValueError("Ungültiger Projektname.")
    return projekte_ordner() / slug / "pruefungen"


def _pfad(slug: str, id: str) -> Path:
    if not isinstance(id, str) or not _ID.fullmatch(id):
        raise ValueError("Ungültige Prüfungs-Kennung.")
    return _ordner(slug) / f"{id}.json"


def sperre(slug: str, id: str) -> threading.Lock:
    """Die Sperre dieser Prüfung. Schlüssel ist der Dateipfad (nicht Slug oder Kennung allein), weil getrennte
    Bereiche (Feature 6) gleiche Slugs haben können."""
    schluessel = str(_pfad(slug, id))
    with _sperren_wache:
        return _sperren.setdefault(schluessel, threading.Lock())


def _lesen(pfad: Path) -> Pruefung | None:
    try:
        return Pruefung.model_validate_json(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # ValidationError ist ein ValueError
        return None


def speichern(slug: str, pruefung: Pruefung) -> None:
    """Schreibt die Prüfung atomar nach projekte/<slug>/pruefungen/<id>.json (legt den Ordner an)."""
    pfad = _pfad(slug, pruefung.id)
    with sperre(slug, pruefung.id):
        atomar_schreiben(pfad, pruefung.model_dump_json(indent=2))


def laden(slug: str, id: str) -> Pruefung | None:
    """Die Prüfung oder None (unbekannt, kaputte Datei oder ungültige Kennung)."""
    try:
        pfad = _pfad(slug, id)
    except ValueError:
        return None
    with sperre(slug, id):
        return _lesen(pfad)


def alle(slug: str) -> list[Pruefung]:
    """Alle lesbaren Prüfungen des Projekts, älteste zuerst (kaputte Dateien werden übersprungen)."""
    try:
        ordner = _ordner(slug)
    except ValueError:
        return []
    if not ordner.is_dir():
        return []
    ergebnis = []
    for d in sorted(ordner.glob("pr-*.json")):
        if _ID.fullmatch(d.stem):
            with sperre(slug, d.stem):
                p = _lesen(d)
            if p:
                ergebnis.append(p)
    return sorted(ergebnis, key=lambda p: (p.erstellt, p.id))


def loeschen(slug: str, id: str) -> bool:
    """Löscht die Prüfung. True, wenn es sie gab."""
    try:
        pfad = _pfad(slug, id)
    except ValueError:
        return False
    with sperre(slug, id):
        try:
            pfad.unlink()
        except FileNotFoundError:
            return False
    return True


# ---------------------------------------------------------------- Ablauf (T007)
#
# Öffentlich: starten, antworten, weiter, beenden, bewerten, zustand, zusammenfassung, laufende.
# Jeder KI-Aufruf geht über waehlen("claude_code").json(prompt, ki_schema(…), []) (FR-016), mit genau einem
# Wiederholungsversuch bei ungültiger Antwort (wie Pipeline._ki_json). Die Regeln aus research.md Punkt 3
# erzwingt das Programm; das Modell liefert nur Urteile. Aufrufe je Prüfung: 1 Plan + höchstens 2 Züge je
# Frage + 1 Bewertung = höchstens 2N + 2 (ohne die automatischen Wiederholungsversuche, SC-005).

PROMPTS = Path(__file__).parent / "prompts"
PLAN_GRENZE = 12_000      # Zeichen Stoff für den Plan-Aufruf (research.md Punkt 4)
THEMA_GRENZE = 3_000      # Zeichen Stoff je Thema für Zug und Bewertung
KEINE_ANTWORT = "(keine Antwort)"
ERSTE_ANTWORT = "(noch nichts: Die aktuelle Antwort ist die erste auf diese Frage.)"


class EingabeFehler(ValueError):
    """Ungültige Eingabe des Nutzers (→ 400): keine Themen, Fragenzahl, Antwort zu lang, Projekt ohne Inhalt."""


class PruefungFehlt(LookupError):
    """Die Prüfung gibt es nicht (→ 404)."""


class VerarbeitungLaeuft(RuntimeError):
    """Für diese Prüfung (bzw. beim Start: für dieses Projekt) läuft gerade schon eine Verarbeitung (→ 409)."""

    def __init__(self, meldung: str = "Die Prüfung wird gerade verarbeitet. Bitte kurz warten."):
        super().__init__(meldung)


class ZustandFehler(RuntimeError):
    """Der Schritt passt nicht zum Zustand der Prüfung (→ 409): beendet, nichts zu wiederholen, Antwort wartet."""


class PruefungLaeuftSchon(ZustandFehler):
    """Im Projekt läuft schon eine Prüfung (→ 409). `id` ist ihre Kennung."""

    def __init__(self, id: str):
        self.id = id
        super().__init__("In diesem Projekt läuft schon eine Prüfung. Setze sie fort oder beende sie zuerst.")


# ---------------------------------------------------------------- Sperren für die Verarbeitung

_verarbeitung: dict[str, threading.Lock] = {}


def _verarbeitungs_sperre(schluessel: Path) -> threading.Lock:
    """Eigene Sperre für die (lange) Verarbeitung, getrennt von `sperre()` der Speicherschicht, die nur
    Lese-/Schreibvorgänge schützt. Schlüssel ist ein Pfad (Datei der Prüfung bzw. Ordner beim Start)."""
    with _sperren_wache:
        return _verarbeitung.setdefault(str(schluessel), threading.Lock())


class _Exklusiv:
    """`with _Exklusiv(pfad):` – sofort VerarbeitungLaeuft, wenn schon jemand arbeitet (kein Warten)."""

    def __init__(self, schluessel: Path, meldung: str | None = None):
        self.lock = _verarbeitungs_sperre(schluessel)
        self.meldung = meldung

    def __enter__(self):
        if not self.lock.acquire(blocking=False):
            raise VerarbeitungLaeuft(*([self.meldung] if self.meldung else []))
        return self

    def __exit__(self, *_):
        self.lock.release()


# ---------------------------------------------------------------- Prompts

_PLATZHALTER = re.compile(r"\{\{(\w+)\}\}")
_SPRACHEN = {"de": "Deutsch", "en": "Englisch", "fr": "Französisch", "it": "Italienisch", "es": "Spanisch",
             "la": "Latein", "ru": "Russisch", "tr": "Türkisch", "hr": "Kroatisch", "sl": "Slowenisch"}


def prompt_bauen(name: str, **werte: str) -> str:
    """Lädt prompts/<name>.md, schneidet den Kommentar am Anfang ab und ersetzt alle {{platzhalter}} in einem
    Durchgang (eingesetzter Fremdtext wird also nie selbst nach Platzhaltern durchsucht). Fehlt ein Wert, ist
    das ein Programmfehler (KeyError)."""
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    if text.lstrip().startswith("<!--"):
        text = text.split("-->", 1)[1].lstrip("\n")

    def ersetzen(m: re.Match) -> str:
        return str(werte[m.group(1)])

    return _PLATZHALTER.sub(ersetzen, text)


def _beispiel(datei: str) -> str:
    return (PROMPTS / "beispiele" / datei).read_text(encoding="utf-8").strip()


def _sprache_wort(code: str) -> str:
    return _SPRACHEN.get((code or "de").split("-")[0].lower(), code or "Deutsch")


def _fach(projekt: Projekt) -> str:
    try:
        return faecher.fach(projekt.meta().fach).name
    except (OSError, ValueError):
        return "Sonstiges"


def _zeile(text: str) -> str:
    """Einzeilig (Titel in Listen sollen keine eigenen Überschriften oder Zeilen einschleusen)."""
    return re.sub(r"\s+", " ", text or "").strip()


def _themen_liste(doc: Dokument, ids: Sequence[str]) -> str:
    titel = {t.id: t.titel for t in doc.themen}
    return "\n".join(f"- `{i}`: {entschaerfen(_zeile(titel.get(i, '(Thema nicht mehr im Projekt)')))}" for i in ids)


def _stoff(doc: Dokument, ids: Sequence[str], gesamt: int) -> str:
    """Stoff der Themen, je Thema mit Überschrift "### Thema `t-…`: Titel", gleichmäßig verteilt, höchstens
    `gesamt` Zeichen, entschärft."""
    titel = {t.id: t.titel for t in doc.themen}
    vorhanden = [i for i in dict.fromkeys(ids) if i in titel]
    if not vorhanden:
        return "(Zu diesem Thema gibt es im Projekt keinen Stoff mehr.)"
    anteil = max(1, (gesamt - 2 * (len(vorhanden) - 1)) // len(vorhanden))
    teile = []
    for i in vorhanden:
        text = material_text(doc, [i], anteil + 64)
        alt = f"## {titel[i]}"
        if text.startswith(alt):
            text = text[len(alt):].lstrip("\n")
        teile.append((f"### Thema `{i}`: {_zeile(titel[i])}\n" + text)[:anteil].rstrip())
    return entschaerfen("\n\n".join(teile)[:gesamt])


# ---------------------------------------------------------------- KI-Aufruf mit einem Wiederholungsversuch

def _ki_json(projekt: Projekt, schritt: str, prompt: str, modell_cls: type[BaseModel],
             regeln: Callable[[BaseModel], list[str]] | None = None,
             nachsicht: Callable[[BaseModel], BaseModel] | None = None):
    """Wie Pipeline._ki_json: Aufruf, Pydantic-Prüfung, Regeln; bei Fehlern genau ein Wiederholungsversuch mit
    dem Fehlertext. Verbindungs-/CLI-Fehler werden nicht wiederholt. Verletzt auch der zweite (schemagültige)
    Versuch nur die Regeln und gibt es `nachsicht`, wird deren Ergebnis genommen (Zwang auf `weiter`)."""
    modell = waehlen("claude_code")  # beim Aufruf nachgeschlagen (monkeypatch in Tests)
    schema = ki_schema(modell_cls)
    p = prompt
    fehler = ""
    for versuch in (1, 2):
        t = time.time()
        roh, obj = None, None
        try:
            roh = modell.json(p, schema, [])
            obj = modell_cls.model_validate(roh)
            probleme = regeln(obj) if regeln else []
            if not probleme:
                _log(projekt, schritt, versuch=versuch, prompt=p, antwort=roh, dauer_s=round(time.time() - t, 1))
                return obj
            fehler = "\n".join(probleme)
        except ValidationError as e:
            fehler = str(e)
        except ModellFehler as e:
            fehler = str(e)
            if "kein gültiges JSON" not in fehler:  # CLI nicht da, Kontingent erschöpft …: nicht wiederholen
                _log(projekt, schritt, versuch=versuch, prompt=p, fehler=fehler)
                raise
        _log(projekt, schritt, versuch=versuch, prompt=p, antwort=roh, fehler=fehler,
             dauer_s=round(time.time() - t, 1))
        if versuch == 2 and obj is not None and nachsicht is not None:
            return nachsicht(obj)
        p = (prompt + "\n\n## Deine letzte Antwort war ungültig\n\n" + fehler[:4000] +
             "\n\nGib eine vollständige, korrigierte Antwort nach dem Schema und den Regeln oben.")
    raise ModellFehler(f"Prüfung ({schritt}): keine gültige Antwort nach 2 Versuchen: {fehler[:500]}")


def _log(projekt: Projekt, schritt: str, **daten) -> None:
    try:
        projekt.log(f"pruefung-{schritt}", {"modell": "claude_code", **daten})
    except OSError:
        pass  # ein fehlendes Protokoll darf die Prüfung nicht stören


# ---------------------------------------------------------------- Hilfen zum Zustand

_WEISS_NICHT = {
    "weiß nicht", "weiss nicht", "ich weiß nicht", "ich weiss nicht", "weiß ich nicht", "weiss ich nicht",
    "ich weiß es nicht", "ich weiss es nicht", "keine ahnung", "ich habe keine ahnung", "hab keine ahnung",
    "i dont know", "i do not know", "dont know", "no idea", "i have no idea",
}


def ist_leer(text: str) -> bool:
    """Leer oder nur „weiß nicht“ / „keine Ahnung“ (ohne Groß-/Kleinschreibung und Satzzeichen)."""
    t = re.sub(r"[^\w\s]", "", (text or "").lower())
    t = re.sub(r"\s+", " ", t).strip()
    return not t or t in _WEISS_NICHT


def _neue_id(slug: str) -> str:
    while True:
        id = "pr-" + secrets.token_hex(4)
        if not _pfad(slug, id).exists():
            return id


def laufende(slug: str) -> Pruefung | None:
    """Die laufende Prüfung des Projekts (höchstens eine) oder None."""
    return next((p for p in reversed(alle(slug)) if p.status == "laeuft"), None)


def _bewertet(pr: Pruefung) -> set[int]:
    return {p.nr for p in pr.punkte}


def _letzte_frage(pr: Pruefung) -> Nachricht | None:
    return next((n for n in reversed(pr.verlauf) if n.art == "pruefer"), None)


def _wartende(pr: Pruefung) -> Nachricht | None:
    """Die Schülerantwort, deren Zug noch fehlt (immer die letzte Nachricht)."""
    if pr.verlauf and pr.verlauf[-1].art == "schueler" and pr.verlauf[-1].status == "wartet":
        return pr.verlauf[-1]
    return None


def _alle_fragen_bewertet(pr: Pruefung) -> bool:
    return bool(pr.plan) and _bewertet(pr) >= {f.nr for f in pr.plan}


def _frage(pr: Pruefung, nr: int) -> PlanFrageGespeichert:
    return next(f for f in pr.plan if f.nr == nr)


def _laden(projekt: Projekt, id: str) -> Pruefung:
    pr = laden(projekt.slug, id)
    if pr is None:
        raise PruefungFehlt("Diese Prüfung gibt es nicht.")
    return pr


def _sichern(projekt: Projekt, pr: Pruefung) -> None:
    """Speichert nach einem KI-Aufruf, aber nur, wenn die Prüfung inzwischen nicht gelöscht wurde."""
    if not _pfad(projekt.slug, pr.id).exists():
        raise PruefungFehlt("Die Prüfung wurde inzwischen gelöscht.")
    speichern(projekt.slug, pr)


def _doc(projekt: Projekt) -> Dokument:
    return projekt.inhalt()


# ---------------------------------------------------------------- Start (Plan-Aufruf)

def starten(projekt: Projekt, themen: Sequence[str], fragen: int = 6) -> Pruefung:
    """Neue Prüfung: Plan-Aufruf, Plan prüfen, speichern, erste Frage in den Verlauf.

    EingabeFehler: Projekt ohne Inhalt, keine/unbekannte Themen, Fragenzahl nicht 3 bis 12.
    PruefungLaeuftSchon: Im Projekt läuft schon eine Prüfung. VerarbeitungLaeuft: Start läuft schon.
    ModellFehler: Plan-Aufruf gescheitert – dann wird nichts angelegt."""
    if isinstance(fragen, bool) or not isinstance(fragen, int) or not 3 <= fragen <= 12:
        raise EingabeFehler("Die Zahl der Fragen muss zwischen 3 und 12 liegen.")
    if not projekt.hat_inhalt():
        raise EingabeFehler("Das Projekt hat noch keinen Inhalt.")
    doc = _doc(projekt)
    ids = list(dict.fromkeys(t for t in (themen or []) if isinstance(t, str)))
    if not ids:
        raise EingabeFehler("Wähle mindestens ein Thema.")
    bekannt = {t.id for t in doc.themen}
    fremd = [i for i in ids if i not in bekannt]
    if fremd:
        raise EingabeFehler(f"Unbekanntes Thema: {', '.join(fremd)}")
    reihenfolge = [t.id for t in doc.themen if t.id in ids]  # Reihenfolge des Projekts

    with _Exklusiv(_ordner(projekt.slug), "Eine Prüfung wird gerade gestartet. Bitte kurz warten."):
        if (lp := laufende(projekt.slug)) is not None:
            raise PruefungLaeuftSchon(lp.id)
        prompt = prompt_bauen("plan", fach=_fach(projekt), sprache=_sprache_wort(doc.projekt.sprache),
                              fragen=str(fragen), themen=_themen_liste(doc, reihenfolge),
                              material=_stoff(doc, reihenfolge, PLAN_GRENZE), beispiel=_beispiel("plan.json"))
        plan = _ki_json(projekt, "plan", prompt, PruefungsPlan, regeln=lambda pl: plan_fehler(pl, reihenfolge, fragen))
        pr = Pruefung(
            id=_neue_id(projekt.slug), erstellt=datetime.now().replace(microsecond=0), themen=reihenfolge,
            fragen_anzahl=fragen, sprache=doc.projekt.sprache or "de",
            plan=[PlanFrageGespeichert(nr=i, thema_id=f.thema_id, frage=f.frage.strip(),
                                       erwartung=[e.strip() for e in f.erwartung])
                  for i, f in enumerate(plan.fragen, 1)],
        )
        pr.verlauf.append(Nachricht(art="pruefer", nr=1, typ="frage", text=pr.plan[0].frage))
        speichern(projekt.slug, pr)
        return pr


def plan_fehler(plan: PruefungsPlan, themen: Sequence[str], fragen: int) -> list[str]:
    """Regeln für den Plan (research.md Punkt 3 d, data-model.md): 1 bis `fragen` Fragen, `thema_id` aus der
    Auswahl, Frage und Erwartungspunkte nicht leer (2 bis 6 Punkte prüft das Schema), keine doppelte Frage."""
    p: list[str] = []
    if not plan.fragen:
        p.append("Der Plan enthält keine Frage. Gib mindestens eine Frage zum Stoff an.")
    if len(plan.fragen) > fragen:
        p.append(f"Der Plan enthält {len(plan.fragen)} Fragen, erlaubt sind höchstens {fragen}.")
    erlaubt = set(themen)
    gesehen: set[str] = set()
    for i, f in enumerate(plan.fragen, 1):
        if f.thema_id not in erlaubt:
            p.append(f"Frage {i}: thema_id {f.thema_id!r} gehört nicht zu den erlaubten Themen "
                     f"({', '.join(themen)}).")
        if not f.frage.strip():
            p.append(f"Frage {i}: Der Fragetext ist leer.")
        if any(not e.strip() for e in f.erwartung):
            p.append(f"Frage {i}: Ein Erwartungspunkt ist leer.")
        if not 2 <= len(f.erwartung) <= 6:
            p.append(f"Frage {i}: erwartung braucht 2 bis 6 Stichpunkte.")
        k = _zeile(f.frage).lower()
        if k and k in gesehen:
            p.append(f"Frage {i}: Diese Frage kommt schon einmal vor.")
        gesehen.add(k)
    return p


# ---------------------------------------------------------------- Antwort (Zug-Aufruf)

def antworten(projekt: Projekt, id: str, text: str) -> Pruefung:
    """Antwort des Schülers auf die aktuelle Frage oder Nachfrage.

    Leere Antwort oder nur „weiß nicht“ auf eine Hauptfrage: 0 Punkte ohne Aufruf, nächste Frage. Sonst wird die
    Antwort zuerst mit Status `wartet` gespeichert und dann der Zug-Aufruf gemacht (auf eine Nachfrage mit
    „(keine Antwort)“, falls leer; dann gilt nur `weiter`). Nach der letzten Frage folgt die Bewertung.
    EingabeFehler (über 4000 Zeichen), PruefungFehlt, VerarbeitungLaeuft, ZustandFehler, ModellFehler."""
    text = text if isinstance(text, str) else ""
    if len(text) > ANTWORT_MAX:
        raise EingabeFehler(f"Die Antwort ist zu lang (höchstens {ANTWORT_MAX} Zeichen). Bitte kürzen.")
    text = text.strip()
    with _Exklusiv(_pfad(projekt.slug, id)):
        pr = _laden(projekt, id)
        if pr.status != "laeuft":
            raise ZustandFehler("Die Prüfung ist schon beendet.")
        if _wartende(pr) is not None:
            raise ZustandFehler("Die letzte Antwort wartet noch auf den Prüfer. Bitte „Weiter versuchen“.")
        frage = _letzte_frage(pr)
        if frage is None or frage.nr in _bewertet(pr):
            raise ZustandFehler("Es gibt gerade keine offene Frage. Bitte „Weiter versuchen“.")
        if frage.typ == "frage" and ist_leer(text):
            pr.verlauf.append(Nachricht(art="schueler", nr=frage.nr, text=text, status="bewertet"))
            pr.punkte.append(PunkteEintrag(nr=frage.nr, punkte=0,
                                           anmerkung="Nicht beantwortet (leer oder „weiß nicht“)."))
            return _nach_punkten(projekt, pr)
        pr.verlauf.append(Nachricht(art="schueler", nr=frage.nr, text=text, status="wartet"))
        speichern(projekt.slug, pr)  # vor dem Aufruf: Bei einem Fehler geht die Antwort nicht verloren
        return _zug(projekt, pr)


def weiter(projekt: Projekt, id: str) -> Pruefung:
    """Wiederholt, was nach einem Fehler fehlt: den Zug zur wartenden Antwort oder die Bewertung nach der letzten
    Frage. ZustandFehler, wenn es nichts zu wiederholen gibt."""
    with _Exklusiv(_pfad(projekt.slug, id)):
        pr = _laden(projekt, id)
        if pr.status == "laeuft":
            if _wartende(pr) is not None:
                return _zug(projekt, pr)
            if _alle_fragen_bewertet(pr):
                return bewerten(projekt, pr, verkuerzt=False)
        raise ZustandFehler("Es gibt nichts zu wiederholen.")


def beenden(projekt: Projekt, id: str) -> Pruefung:
    """Beendet die Prüfung vorzeitig: Bewertet werden nur Fragen mit Punkten (eine wartende Antwort oder eine
    offene Nachfrage zählt nicht). Waren schon alle Fragen bewertet, ist es keine verkürzte Prüfung."""
    with _Exklusiv(_pfad(projekt.slug, id)):
        pr = _laden(projekt, id)
        if pr.status != "laeuft":
            raise ZustandFehler("Die Prüfung ist schon beendet.")
        return bewerten(projekt, pr, verkuerzt=not _alle_fragen_bewertet(pr))


def _zug(projekt: Projekt, pr: Pruefung) -> Pruefung:
    """Zug-Aufruf für die wartende Antwort, Regeln erzwingen, Ergebnis in den Verlauf (Aufrufer hält die Sperre)."""
    antwort = _wartende(pr)
    assert antwort is not None
    nr = antwort.nr
    f = _frage(pr, nr)
    zur_frage = [n for n in pr.verlauf if n.nr == nr]
    hatte_nachfrage = any(n.art == "pruefer" and n.typ == "nachfrage" for n in zur_frage)
    auf_nachfrage = _letzte_frage(pr).typ == "nachfrage"
    leer = ist_leer(antwort.text)
    if leer and not auf_nachfrage:  # kann nur bei alten Daten passieren: wie in antworten() ohne Aufruf
        antwort.status = "bewertet"
        pr.punkte.append(PunkteEintrag(nr=nr, punkte=0, anmerkung="Nicht beantwortet (leer oder „weiß nicht“)."))
        return _nach_punkten(projekt, pr)
    nachfrage_erlaubt = not hatte_nachfrage and not leer

    dialog = []
    for n in zur_frage[:-1]:  # ohne die aktuelle Antwort
        if n.art == "pruefer" and n.typ == "frage":
            continue
        if n.art == "pruefer":
            dialog.append(f"Prüfer (Nachfrage): {n.text}")
        else:
            dialog.append(f"Schüler: {n.text or KEINE_ANTWORT}")
    doc = _doc(projekt)
    prompt = prompt_bauen(
        "zug", fach=_fach(projekt), sprache=_sprache_wort(pr.sprache), frage=f.frage,
        erwartung="\n".join(f"- {e}" for e in f.erwartung),
        material=_stoff(doc, [f.thema_id], THEMA_GRENZE),
        dialog=entschaerfen("\n".join(dialog) if dialog else ERSTE_ANTWORT),
        antwort=KEINE_ANTWORT if leer else entschaerfen(antwort.text),
        nachfrage_erlaubt="ja" if nachfrage_erlaubt else "nein",
        beispiel_nachfrage=_beispiel("zug_nachfrage.json"), beispiel_weiter=_beispiel("zug_weiter.json"),
    )

    def regeln(z: Pruefungszug) -> list[str]:
        if z.aktion == "nachfrage" and not nachfrage_erlaubt:
            return ["Eine Nachfrage ist hier nicht erlaubt (höchstens eine Nachfrage je Frage, bzw. keine Antwort "
                    "auf die Nachfrage). Wähle aktion \"weiter\" mit punkte 0, 1 oder 2 und text null."]
        return []

    def nachsicht(z: Pruefungszug) -> Pruefungszug:  # zweite Nachfrage trotz Verbot: Zwang auf weiter
        punkte = z.punkte if z.punkte is not None else 1
        return Pruefungszug(aktion="weiter", punkte=punkte,
                            anmerkung=(z.anmerkung + " " if z.anmerkung else "") + "(Weiter vom Programm erzwungen.)")

    zug = _ki_json(projekt, "zug", prompt, Pruefungszug, regeln=regeln, nachsicht=nachsicht)

    antwort.status = "bewertet"
    if zug.aktion == "nachfrage":
        pr.verlauf.append(Nachricht(art="pruefer", nr=nr, typ="nachfrage", text=zug.text.strip()))
        _sichern(projekt, pr)
        return pr
    pr.punkte.append(PunkteEintrag(nr=nr, punkte=zug.punkte, anmerkung=zug.anmerkung.strip()))
    return _nach_punkten(projekt, pr)


def _nach_punkten(projekt: Projekt, pr: Pruefung) -> Pruefung:
    """Nächste Frage aus dem Plan stellen oder, nach der letzten, bewerten. Die Frage kommt immer aus dem Plan,
    nie vom Modell. Speichert vor der Bewertung, damit ein Fehler dort keine Punkte kostet."""
    offen = [f for f in pr.plan if f.nr not in _bewertet(pr)]
    if offen:
        pr.verlauf.append(Nachricht(art="pruefer", nr=offen[0].nr, typ="frage", text=offen[0].frage))
    _sichern(projekt, pr)
    if offen:
        return pr
    return bewerten(projekt, pr, verkuerzt=False)


# ---------------------------------------------------------------- Bewertung

def bewerten(projekt: Projekt, pr: Pruefung, verkuerzt: bool) -> Pruefung:
    """Bewertungs-Aufruf für die Fragen mit Punkten, Note vom Programm (ergebnis_rechnen), Ergebnis und Status
    speichern. Ohne beantwortete Frage kein Aufruf („Nichts zu bewerten.“). Der Aufrufer hält die Sperre der
    Prüfung (antworten, weiter, beenden); direkt nur mit einer frisch geladenen Prüfung verwenden."""
    punkte = {p.nr: p for p in pr.punkte}
    beantwortet = [f for f in pr.plan if f.nr in punkte]
    ergebnis = ergebnis_rechnen(pr.plan, pr.punkte, verkuerzt)
    doc = _doc(projekt)
    if beantwortet:
        prompt = prompt_bauen(
            "bewertung", fach=_fach(projekt), sprache=_sprache_wort(pr.sprache),
            verkuerzt="ja" if verkuerzt else "nein", themen=_themen_liste(doc, pr.themen),
            uebersicht="\n".join(f"- Frage {f.nr} · Thema `{f.thema_id}` · {punkte[f.nr].punkte} von 2 Punkten"
                                 for f in beantwortet),
            material=_stoff(doc, [f.thema_id for f in beantwortet],
                            THEMA_GRENZE * len({f.thema_id for f in beantwortet})),
            dialog=_bewertungs_dialog(pr, beantwortet), beispiel=_beispiel("bewertung.json"),
        )
        nrs = [f.nr for f in beantwortet]
        bew = _ki_json(projekt, "bewertung", prompt, Pruefungsbewertung,
                       regeln=lambda b: bewertung_fehler(b, pr.themen, nrs))
        titel = {t.id: t.titel for t in doc.themen}
        ergebnis.begruendung = bew.begruendung.strip()
        luecken, gesehen = [], set()
        for lu in bew.luecken:
            if lu.thema_id not in gesehen:
                gesehen.add(lu.thema_id)
                luecken.append(ErgebnisLuecke(thema_id=lu.thema_id, hinweis=lu.hinweis.strip(),
                                              titel=titel.get(lu.thema_id, "")))
        ergebnis.luecken = luecken
        ergebnis.rueckmeldungen = sorted(
            (ErgebnisRueckmeldung(nr=r.nr, punkte=punkte[r.nr].punkte, fehlte=r.fehlte.strip(),
                                  stoff_hinweis=r.stoff_hinweis.strip()) for r in bew.rueckmeldungen),
            key=lambda r: r.nr)
    pr.ergebnis = ergebnis
    pr.status = "verkuerzt" if verkuerzt else "abgeschlossen"
    pr.abgeschlossen = datetime.now().replace(microsecond=0)
    _sichern(projekt, pr)
    return pr


def _bewertungs_dialog(pr: Pruefung, beantwortet: Sequence[PlanFrageGespeichert]) -> str:
    punkte = {p.nr: p for p in pr.punkte}
    teile = []
    for f in beantwortet:
        z = [f"### Frage {f.nr} (Thema `{f.thema_id}`)", f"Frage: {f.frage}", "Erwartung:",
             *[f"- {e}" for e in f.erwartung]]
        for n in pr.verlauf:
            if n.nr != f.nr or (n.art == "pruefer" and n.typ == "frage"):
                continue
            z.append(f"Prüfer (Nachfrage): {n.text}" if n.art == "pruefer" else f"Schüler: {n.text or KEINE_ANTWORT}")
        if punkte[f.nr].anmerkung:
            z.append(f"Anmerkung des Prüfers: {punkte[f.nr].anmerkung}")
        teile.append("\n".join(z))
    return entschaerfen("\n\n".join(teile))


def bewertung_fehler(b: Pruefungsbewertung, themen: Sequence[str], nrs: Sequence[int]) -> list[str]:
    """Regeln für die Bewertung: `thema_id` aus der Auswahl, je beantworteter Frage genau eine Rückmeldung mit
    einer `nr` aus dem Plan, höchstens 5 Lücken (Schema)."""
    p: list[str] = []
    erlaubt = set(themen)
    for lu in b.luecken:
        if lu.thema_id not in erlaubt:
            p.append(f"luecken: thema_id {lu.thema_id!r} gehört nicht zu den erlaubten Themen ({', '.join(themen)}).")
    gezaehlt: dict[int, int] = {}
    for r in b.rueckmeldungen:
        gezaehlt[r.nr] = gezaehlt.get(r.nr, 0) + 1
    fremd = sorted(n for n in gezaehlt if n not in nrs)
    doppelt = sorted(n for n, k in gezaehlt.items() if k > 1)
    fehlt = [n for n in nrs if n not in gezaehlt]
    if fremd:
        p.append(f"rueckmeldungen: Fragen {fremd} wurden nicht beantwortet; erlaubt sind nur nr {list(nrs)}.")
    if doppelt:
        p.append(f"rueckmeldungen: Zu den Fragen {doppelt} gibt es mehr als eine Rückmeldung.")
    if fehlt:
        p.append(f"rueckmeldungen: Zu den Fragen {fehlt} fehlt die Rückmeldung.")
    return p


# ---------------------------------------------------------------- Antwort an die Oberfläche

def _hinweise(pr: Pruefung) -> list[str]:
    h = []
    if pr.plan and len(pr.plan) < pr.fragen_anzahl:
        h.append(f"Der Stoff der gewählten Themen reicht nur für {len(pr.plan)} statt {pr.fragen_anzahl} Fragen.")
    return h


def zustand(pr: Pruefung, projekt: Projekt | None = None) -> dict:
    """Zustand für die Oberfläche (contracts/api.md). Plan (Erwartungspunkte) und interne Punkte/Anmerkungen
    sind nie enthalten. Mit `projekt` bekommen die Lücken ihren Link zur Lernseite; Themen, die es im Projekt
    nicht mehr gibt, bekommen keinen Link (mit Hinweis)."""
    hinweise = _hinweise(pr)
    ergebnis = None
    if pr.ergebnis is not None:
        ergebnis = pr.ergebnis.model_dump(mode="json")
        titel: dict[str, str] | None = None
        if projekt is not None:
            try:
                titel = {t.id: t.titel for t in _doc(projekt).themen}
            except (OSError, ValueError):
                titel = {}
        fehlen = False
        for lu in ergebnis["luecken"]:
            if titel is None:
                lu["link"] = None
            elif lu["thema_id"] in titel:
                lu["titel"] = titel[lu["thema_id"]]
                lu["link"] = f"#/p/{projekt.slug}/vorschau/{lu['thema_id']}"
            else:
                lu["link"] = None
                lu["titel"] = lu["titel"] or lu["thema_id"]
                fehlen = True
        if fehlen:
            hinweise.append("Einige Themen gibt es im Projekt nicht mehr, ihre Links entfallen.")
    laeuft = pr.status == "laeuft"
    frage = _letzte_frage(pr)
    return {
        "id": pr.id,
        "status": pr.status,
        "erstellt": pr.erstellt.isoformat(),
        "abgeschlossen": pr.abgeschlossen.isoformat() if pr.abgeschlossen else None,
        "themen": list(pr.themen),
        "fragen_gewuenscht": pr.fragen_anzahl,
        "fragen_anzahl": len(pr.plan) or pr.fragen_anzahl,
        "aktuelle_frage": frage.nr if laeuft and frage else None,
        "verlauf": [n.model_dump(mode="json", exclude_none=True) for n in pr.verlauf],
        "wartet": laeuft and (_wartende(pr) is not None or _alle_fragen_bewertet(pr)),
        "ergebnis": ergebnis,
        "hinweis": " ".join(hinweise) or None,
    }


def zusammenfassung(pr: Pruefung, projekt: Projekt | None = None) -> dict:
    """Eintrag der Liste früherer Prüfungen: {id, erstellt, status, themen: [Titel], fragen, note, note_name}."""
    titel: dict[str, str] = {}
    if projekt is not None:
        try:
            titel = {t.id: t.titel for t in _doc(projekt).themen}
        except (OSError, ValueError):
            titel = {}
    e = pr.ergebnis
    return {"id": pr.id, "erstellt": pr.erstellt.isoformat(), "status": pr.status,
            "themen": [titel.get(i, i) for i in pr.themen], "fragen": pr.fragen_anzahl,
            "note": e.note if e else None, "note_name": e.note_name if e else None}
