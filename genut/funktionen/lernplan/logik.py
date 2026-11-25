"""Logik des Lernplaners (specs/004-lernplaner/research.md Punkte 1 bis 4).

Teil 1 (dieser Teil) besteht nur aus reinen, deterministischen Funktionen ohne Dateizugriff:
Lerntage, Teilen großer Themen, Verteilen, Neu verteilen und die Plan-Antwort für die Oberfläche.
Die Speicherschicht (T007) kommt unten als eigener Abschnitt dazu.

Begriffe:
- *Einheiten* eines Themas: Liste ihrer Lasten in fester Reihenfolge (`genut.themen.einheiten`). Ein Thema
  ohne Inhalt zählt als eine Einheit der Last 1 (sonst gäbe es keinen gültigen Bereich `[von, bis)`).
- *Stück*: ungeteiltes Thema oder Teil eines geteilten Themas, Einheitenbereich `[von, bis)`.
- `lasten`: geordnetes Mapping `(projekt, thema_id) -> Einheitenlasten` in Planreihenfolge
  (Projekte wie gewählt, Themen wie im Projekt), nur die gewählten (nicht ausgenommenen) Themen.
"""
from __future__ import annotations

import math
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from fractions import Fraction
from typing import Iterable, Mapping, Sequence, TypedDict

from pydantic import ValidationError

from ...config import projekte_ordner
from ...projekt import Projekt, atomar_schreiben
from ...schema import Dokument
from ...themen import einheiten as _thema_einheiten
from .schema import Erledigt, Lernplan, Themenverweis, Zuordnung

Schluessel = tuple[str, str]  # (projekt, thema_id)


class KeinLerntag(ValueError):
    """Zwischen max(start, heute) und dem Tag vor dem Termin liegt kein gewählter Wochentag."""

    def __init__(self, meldung: str = "Bis zum Prüfungstermin gibt es keinen Lerntag mehr. "
                                      "Wähle andere Wochentage oder einen späteren Termin."):
        super().__init__(meldung)


def heute() -> date:
    """Das heutige Datum (in Tests per monkeypatch ersetzbar)."""
    return date.today()


# ---------------------------------------------------------------- Lerntage

def lerntage(start: date, termin: date, wochentage: Iterable[int], heute: date) -> list[date]:
    """Alle Daten von max(start, heute) bis termin - 1 Tag mit gewähltem Wochentag (Montag = 0).

    Der Prüfungstag zählt nie. Der letzte Lerntag ist (ab zwei Lerntagen) Wiederholung."""
    wt = set(wochentage)
    tag = max(start, heute)
    tage: list[date] = []
    while tag < termin:
        if tag.weekday() in wt:
            tage.append(tag)
        tag += timedelta(days=1)
    return tage


# ---------------------------------------------------------------- Stücke und Teilen

@dataclass(frozen=True)
class Stueck:
    """Ein Stück vor dem Verteilen: Einheitenbereich [von, bis) eines Themas mit seiner Last."""
    projekt: str
    thema_id: str
    von: int
    bis: int
    last: float
    teil: int = 1
    teile: int = 1

    @property
    def schluessel(self) -> Schluessel:
        return (self.projekt, self.thema_id)


def _norm(einheiten: Sequence[float]) -> list[float]:
    return [float(x) for x in einheiten] or [1.0]


def bereich_last(einheiten: Sequence[float], von: int, bis: int) -> float:
    """Last des Einheitenbereichs [von, bis). Umfasst er das ganze Thema, mindestens 1 (wie `themen.last`)."""
    e = _norm(einheiten)
    s = sum(e[von:bis])
    return max(1.0, s) if von <= 0 and bis >= len(e) else s


@dataclass
class _Gruppe:
    """Offener Teil eines Themas: ein oder mehrere zusammenhängende Einheitenabschnitte."""
    schluessel: Schluessel
    abschnitte: list[tuple[int, list[float]]]  # (Index der ersten Einheit, Lasten)
    ganz: bool  # das ganze Thema ist offen (dann Last mindestens 1)
    last: float = field(init=False)

    def __post_init__(self):
        s = sum(sum(e) for _, e in self.abschnitte)
        self.last = max(1.0, s) if self.ganz else s


def _bezugslast(gruppen: Sequence[_Gruppe], D: int) -> Fraction:
    T = sum((Fraction(g.last) for g in gruppen), Fraction(0))
    return T / min(max(1, D), len(gruppen))


def _teile_bilden(g: _Gruppe, k: int) -> list[tuple[int, int, float]]:
    """Gierig an Einheitengrenzen in höchstens k Teile: Ein Teil wird geschlossen, sobald die kumulierte Last
    das Ziel j·L/k erreicht hat oder die nächste Einheit sie weiter vom Ziel entfernen würde. Der letzte Teil
    nimmt den Rest. Abschnittsgrenzen (bei teilweise erledigten Themen) schließen immer einen Teil."""
    if k <= 1:
        return [(a, a + len(e), float(sum(e))) for a, e in g.abschnitte]
    z = Fraction(g.last) / k
    teile: list[tuple[int, int, float]] = []
    j, kum = 1, Fraction(0)
    for a, e in g.abschnitte:
        von, summe, anzahl = a, Fraction(0), 0
        for i, u in enumerate(e):
            u = Fraction(u)
            if anzahl and j < k:
                ziel = j * z
                if kum >= ziel or abs(kum + u - ziel) > abs(kum - ziel):
                    teile.append((von, a + i, float(summe)))
                    j += 1
                    von, summe, anzahl = a + i, Fraction(0), 0
            summe += u
            kum += u
            anzahl += 1
        if anzahl:
            teile.append((von, a + len(e), float(summe)))
    return teile


def _teilen_gruppen(gruppen: Sequence[_Gruppe], D: int) -> list[Stueck]:
    if not gruppen:
        return []
    oe = _bezugslast(gruppen, D)
    stuecke: list[Stueck] = []
    for g in gruppen:
        L = Fraction(g.last)
        k = math.ceil(L / oe) if L > Fraction(3, 2) * oe else 1
        teile = _teile_bilden(g, k)
        n = len(teile)
        for nr, (von, bis, l) in enumerate(teile, 1):
            stuecke.append(Stueck(g.schluessel[0], g.schluessel[1], von, bis,
                                  g.last if (g.ganz and n == 1) else l, nr, n))
    return stuecke


def _eintraege(themen) -> list[tuple[Schluessel, Sequence[float]]]:
    return list(themen.items()) if isinstance(themen, Mapping) else [(tuple(k), v) for k, v in themen]


def bezugslast(themen: Mapping[Schluessel, Sequence[float]], D: int) -> float:
    """Ø = T / min(D, N) (research.md Punkt 1, Schritt 0), D = Lerntage ohne Wiederholung (mindestens 1)."""
    gruppen = [_Gruppe(k, [(0, _norm(e))], True) for k, e in _eintraege(themen)]
    return float(_bezugslast(gruppen, D)) if gruppen else 0.0


def teilen(themen: Mapping[Schluessel, Sequence[float]] | Iterable[tuple[Schluessel, Sequence[float]]],
           D: int) -> list[Stueck]:
    """Schritt 0: Themen mit Last > 1,5 × Ø in ceil(L / Ø) Teile an Einheitengrenzen, Ø = T / min(D, N).

    `themen`: (projekt, thema_id) -> Einheitenlasten, in Planreihenfolge. `D`: Lerntage ohne den
    Wiederholungstag (bei nur einem Lerntag 0, dann wird nichts geteilt). Ergebnis: Stücke in Reihenfolge."""
    return _teilen_gruppen([_Gruppe(k, [(0, _norm(e))], True) for k, e in _eintraege(themen)], D)


# ---------------------------------------------------------------- Verteilen

def _tagesindizes(stuecke: Sequence[Stueck], D: int) -> list[int]:
    Np = len(stuecke)
    if D < Np:
        # Mittelpunkt-Regel: Tag j = floor(M_i / T * D), exakt mit Brüchen gerechnet
        T = sum((Fraction(s.last) for s in stuecke), Fraction(0))
        idx, kum = [], Fraction(0)
        for s in stuecke:
            l = Fraction(s.last)
            idx.append(min(math.floor((kum + l / 2) * D / T), D - 1))
            kum += l
        # Lücken schließen: der spätere Teil rückt direkt hinter seinen Vorgänger
        for i in range(1, Np):
            if stuecke[i].schluessel == stuecke[i - 1].schluessel and idx[i] > idx[i - 1] + 1:
                idx[i] = idx[i - 1] + 1
        # kein leerer Anfang: alles um die Zahl der leeren Tage nach vorn ziehen
        v = idx[0]
        return [j - v for j in idx]
    # D >= N': Stücke eines Themas am Stück, Thema g beginnt an s_g = P_g + floor(g (D - N') / G)
    gruppen: list[int] = []  # Zahl der Stücke je Thema
    for i, s in enumerate(stuecke):
        if i and s.schluessel == stuecke[i - 1].schluessel:
            gruppen[-1] += 1
        else:
            gruppen.append(1)
    G = len(gruppen)
    idx, P = [], 0
    for g, n in enumerate(gruppen):
        s_g = P + (g * (D - Np)) // G
        idx.extend(range(s_g, s_g + n))
        P += n
    return idx


def verteilen(stuecke: Sequence[Stueck], tage: Sequence[date]) -> list[Zuordnung]:
    """Verteilt die Stücke (in Reihenfolge) auf die Lerntage `tage` (der letzte ist Wiederholung).

    Bei nur einem Lerntag liegen alle Stücke auf ihm. Danach werden Teile desselben Themas, die auf demselben
    Tag liegen und aneinandergrenzen, zusammengelegt und je Thema neu nummeriert (k/n).
    Ergebnis: Zuordnungen in Stückreihenfolge (`urspruenglich` = None). Ohne Lerntag: `KeinLerntag`."""
    if not tage:
        raise KeinLerntag()
    stuecke = list(stuecke)
    if not stuecke:
        return []
    idx = [0] * len(stuecke) if len(tage) == 1 else _tagesindizes(stuecke, len(tage) - 1)

    # Zusammenlegen: [schluessel, von, bis, tagindex]
    zusammen: list[list] = []
    for s, j in zip(stuecke, idx):
        z = zusammen[-1] if zusammen else None
        if z and z[0] == s.schluessel and z[3] == j and z[2] == s.von:
            z[2] = s.bis
        else:
            zusammen.append([s.schluessel, s.von, s.bis, j])

    ergebnis: list[Zuordnung] = []
    i = 0
    while i < len(zusammen):
        k = i
        while k < len(zusammen) and zusammen[k][0] == zusammen[i][0]:
            k += 1
        n = k - i
        for nr, (sch, von, bis, j) in enumerate(zusammen[i:k], 1):
            ergebnis.append(Zuordnung(projekt=sch[0], thema_id=sch[1], datum=tage[j], urspruenglich=None,
                                      teil=nr, teile=n, von=von, bis=bis))
        i = k
    return ergebnis


# ---------------------------------------------------------------- Neu verteilen

def _abschnitte(n: int, belegt: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """Zusammenhängende Bereiche von [0, n), die von keinem der Bereiche in `belegt` abgedeckt sind."""
    frei = [True] * n
    for von, bis in belegt:
        for u in range(max(0, von), min(n, bis)):
            frei[u] = False
    bereiche, a = [], None
    for u in range(n + 1):
        if u < n and frei[u]:
            if a is None:
                a = u
        elif a is not None:
            bereiche.append((a, u))
            a = None
    return bereiche


def neu_verteilen(plan: Lernplan, lasten: Mapping[Schluessel, Sequence[float]], heute: date) -> Lernplan:
    """Verteilt den offenen Teil des Plans neu auf die Lerntage ab `heute` (research.md Punkt 4).

    - Fest bleiben erledigte Stücke (Datum, Bereich; Bereiche werden auf die heutige Zahl der Einheiten gekürzt,
      ganz außerhalb liegende fallen weg). Themen, die nicht in `lasten` stehen, fallen aus dem Plan.
    - Alle offenen Einheiten (auch überfällige und neue) werden mit dem Verfahren aus Punkt 1 neu geteilt und
      verteilt. Die Teilnummern zählen nach den erledigten Teilen weiter (erledigt 1/3, neu 2/3 und 3/3).
    - `urspruenglich` = altes Datum der Einheit, mit der ein neues Stück beginnt, wenn sich das Datum ändert.
    - Gibt es keinen Lerntag mehr vor dem Termin: `KeinLerntag`, der Plan bleibt unverändert.
    Auf einen Plan ohne Zuordnung angewandt ist das die Erstverteilung. Gibt einen neuen Plan zurück."""
    tage = lerntage(plan.start, plan.termin, plan.wochentage, heute)
    if not tage:
        raise KeinLerntag()

    erledigt = {(e.projekt, e.thema_id, e.von, e.bis) for e in plan.erledigt}
    alt: dict[Schluessel, list[Zuordnung]] = {}
    for z in plan.zuordnung:
        alt.setdefault((z.projekt, z.thema_id), []).append(z)

    fest: dict[Schluessel, list[Zuordnung]] = {}
    geaendert: dict[Schluessel, bool] = {}
    gruppen: list[_Gruppe] = []
    alte_offene: dict[Schluessel, list[Zuordnung]] = {}
    for sch, roh in _eintraege(lasten):
        e = _norm(roh)
        n = len(e)
        alte = alt.get(sch, [])
        f: list[Zuordnung] = []
        gekuerzt = False
        for z in sorted(alte, key=lambda z: (z.von, z.teil)):
            if (z.projekt, z.thema_id, z.von, z.bis) not in erledigt:
                continue
            if z.von >= n:
                gekuerzt = True
                continue
            if z.bis > n:
                gekuerzt = True
                z = z.model_copy(update={"bis": n})
            f.append(z)
        fest[sch] = f
        alte_offene[sch] = [z for z in alte if (z.projekt, z.thema_id, z.von, z.bis) not in erledigt]
        bereiche = _abschnitte(n, [(z.von, z.bis) for z in f])
        geaendert[sch] = bool(bereiche) or gekuerzt or len(f) != len(alte)
        if bereiche:
            gruppen.append(_Gruppe(sch, [(a, e[a:b]) for a, b in bereiche], ganz=not f))

    neu: dict[Schluessel, list[Zuordnung]] = {}
    for z in verteilen(_teilen_gruppen(gruppen, len(tage) - 1), tage):
        sch = (z.projekt, z.thema_id)
        vorher = next((o for o in alte_offene.get(sch, []) if o.von <= z.von < o.bis), None)
        if vorher is None:
            urspr = None
        elif vorher.datum != z.datum:
            urspr = vorher.datum
        else:
            urspr = vorher.urspruenglich
        neu.setdefault(sch, []).append(z.model_copy(update={"urspruenglich": urspr}))

    zuordnung: list[Zuordnung] = []
    for sch, _ in _eintraege(lasten):
        f, n_ = fest[sch], neu.get(sch, [])
        if not geaendert[sch]:
            zuordnung.extend(sorted(alt.get(sch, []), key=lambda z: (z.teil, z.von)))
            continue
        teile = len(f) + len(n_)
        zuordnung.extend(z.model_copy(update={"teil": nr, "teile": teile}) for nr, z in enumerate(f + n_, 1))

    erledigt_neu = [Erledigt(projekt=z.projekt, thema_id=z.thema_id, von=z.von, bis=z.bis)
                    for sch in fest for z in fest[sch]]
    return plan.model_copy(update={"zuordnung": zuordnung, "erledigt": erledigt_neu})


# ---------------------------------------------------------------- Projektdaten (rein, ohne Dateizugriff)

class ThemaDaten(TypedDict):
    id: str
    titel: str
    einheiten: list[float]


class Projektdaten(TypedDict):
    name: str
    themen: list[ThemaDaten]


def projektdaten(name: str, doc: Dokument) -> Projektdaten:
    """Was `plan_antwort` und `lasten_aus` von einem Projekt brauchen (Themen in Projektreihenfolge)."""
    return {"name": name,
            "themen": [{"id": t.id, "titel": t.titel, "einheiten": _thema_einheiten(t, doc)} for t in doc.themen]}


def _verweis(a) -> Schluessel:
    return (a.projekt, a.thema_id) if hasattr(a, "projekt") else (a[0], a[1])


def lasten_aus(projekte: Mapping[str, Projektdaten | None], slugs: Sequence[str],
               ausgenommen: Iterable = ()) -> dict[Schluessel, list[float]]:
    """`lasten` für `teilen`/`neu_verteilen`: Themen der Projekte in `slugs` (in dieser Reihenfolge), ohne
    ausgenommene (`Themenverweis` oder (projekt, thema_id)). Fehlende Projekte werden übersprungen."""
    weg = {_verweis(a) for a in ausgenommen}
    out: dict[Schluessel, list[float]] = {}
    for slug in slugs:
        p = projekte.get(slug)
        if not p:
            continue
        for t in p["themen"]:
            if (slug, t["id"]) not in weg:
                out[(slug, t["id"])] = list(t["einheiten"])
    return out


# ---------------------------------------------------------------- Plan-Antwort

def _datum_text(d: date) -> str:
    return f"{d:%d.%m.%Y}"


def plan_antwort(plan: Lernplan, projekte: Mapping[str, Projektdaten | None], heute: date) -> dict:
    """Plan-Antwort laut data-model.md (alle Daten als ISO-Text, JSON-fertig).

    `projekte`: slug -> Projektdaten (siehe `projektdaten`) für die Projekte des Plans; fehlt ein Slug oder ist
    der Wert None, gilt das Projekt als gelöscht (Hinweis statt Fehler)."""
    ordnung: dict[Schluessel, int] = {}
    info: dict[Schluessel, tuple[str, str, list[float]]] = {}
    for slug in plan.projekte:
        p = projekte.get(slug)
        if not p:
            continue
        for t in p["themen"]:
            sch = (slug, t["id"])
            ordnung.setdefault(sch, len(ordnung))
            info[sch] = (p["name"], t["titel"], _norm(t["einheiten"]))

    hinweise: list[str] = []
    for slug in plan.projekte:
        if not projekte.get(slug):
            hinweise.append(f"Das Projekt „{slug}“ gibt es nicht mehr. Seine Themen sind aus dem Plan genommen.")

    erledigt = {(e.projekt, e.thema_id, e.von, e.bis) for e in plan.erledigt}
    stuecke: list[dict] = []
    weg_themen: dict[str, set[str]] = {}
    gekuerzt: list[Schluessel] = []
    belegt: dict[Schluessel, list[tuple[int, int]]] = {}
    for z in plan.zuordnung:
        sch = (z.projekt, z.thema_id)
        if z.projekt not in plan.projekte or not projekte.get(z.projekt):
            continue  # entferntes oder gelöschtes Projekt (Hinweis oben)
        if sch not in info:
            weg_themen.setdefault(z.projekt, set()).add(z.thema_id)
            continue
        name, titel, e = info[sch]
        n = len(e)
        if z.bis > n and sch not in gekuerzt:
            gekuerzt.append(sch)
        if z.von >= n:
            continue
        bis = min(z.bis, n)
        belegt.setdefault(sch, []).append((z.von, bis))
        ist_erledigt = (z.projekt, z.thema_id, z.von, z.bis) in erledigt
        status = "erledigt" if ist_erledigt else ("ueberfaellig" if z.datum < heute else "offen")
        stuecke.append({
            "projekt": z.projekt, "projekt_name": name, "thema_id": z.thema_id, "titel": titel,
            "teil": z.teil, "teile": z.teile, "von": z.von, "bis": bis,
            "bis_gespeichert": z.bis,
            "umfang": round(bereich_last(e, z.von, bis), 2),
            "datum": z.datum.isoformat(), "status": status,
            "urspruenglich": z.urspruenglich.isoformat() if z.urspruenglich else None,
            "link": f"#/p/{z.projekt}/vorschau/{z.thema_id}",
        })
    for slug in plan.projekte:
        if slug in weg_themen:
            name = projekte[slug]["name"]
            k = len(weg_themen[slug])
            hinweise.append(f"Ein Thema aus „{name}“ gibt es nicht mehr. Es ist aus dem Plan genommen." if k == 1
                            else f"{k} Themen aus „{name}“ gibt es nicht mehr. Sie sind aus dem Plan genommen.")
    for sch in gekuerzt:
        hinweise.append(f"„{info[sch][1]}“ ist kürzer geworden. „Neu verteilen“ passt den Plan an.")

    # neue Themen und neue Einheiten, die noch in keinem Stück liegen
    weg = {_verweis(a) for a in plan.ausgenommen}
    unverteilt: list[dict] = []
    for sch in ordnung:
        if sch in weg:
            continue
        name, titel, e = info[sch]
        for von, bis in _abschnitte(len(e), belegt.get(sch, [])):
            unverteilt.append({
                "projekt": sch[0], "projekt_name": name, "thema_id": sch[1], "titel": titel,
                "teil": 1, "teile": 1, "von": von, "bis": bis, "umfang": round(bereich_last(e, von, bis), 2),
                "datum": None, "status": "offen", "urspruenglich": None,
                "link": f"#/p/{sch[0]}/vorschau/{sch[1]}",
            })
    if unverteilt:
        hinweise.append("Neue Inhalte sind noch nicht verteilt. „Neu verteilen“ nimmt sie in den Plan auf.")

    # Tage: Lerntage von start bis zum Tag vor dem Termin, dazu Tage, auf denen noch Stücke liegen
    alle = lerntage(plan.start, plan.termin, plan.wochentage, plan.start)
    letzter = alle[-1] if alle else None
    stuecke.sort(key=lambda s: (s["datum"], ordnung[(s["projekt"], s["thema_id"])], s["von"]))
    je_tag: dict[str, list[dict]] = {}
    for s in stuecke:
        je_tag.setdefault(s["datum"], []).append(s)
    daten = sorted(set(alle) | {date.fromisoformat(d) for d in je_tag})

    T = sum(s["umfang"] for s in stuecke)
    D = max(1, len(alle) - 1)
    schnitt = T / min(D, len(stuecke)) if stuecke else 0.0
    wdh_haken = set(plan.wiederholung_erledigt)
    tage: list[dict] = []
    volle: list[date] = []
    for d in daten:
        themen = je_tag.get(d.isoformat(), [])
        last = round(sum(s["umfang"] for s in themen), 2)
        wiederholung = not themen or d == letzter
        if not themen and d < heute and d not in wdh_haken:
            wiederholung = False  # vergangener Tag ohne Thema und ohne Haken: „frei“
        voll = bool(themen) and last > 2 * schnitt
        if voll and d >= heute and any(s["status"] != "erledigt" for s in themen):
            volle.append(d)
        tage.append({"datum": d.isoformat(), "wochentag": d.weekday(), "themen": themen,
                     "wiederholung": wiederholung, "wiederholung_erledigt": wiederholung and d in wdh_haken,
                     "last": last, "voll": voll})

    erl = sum(1 for s in stuecke if s["status"] == "erledigt")
    wdh_gesamt = sum(1 for t in tage if t["wiederholung"])
    wdh_erl = sum(1 for t in tage if t["wiederholung_erledigt"])
    ueberfaellig = sum(1 for s in stuecke if s["status"] == "ueberfaellig")
    offen = erl < len(stuecke) or bool(unverteilt)

    warnungen: list[str] = []
    rest = lerntage(plan.start, plan.termin, plan.wochentage, heute)
    if offen and len(rest) == 1:
        warnungen.append("Sehr wenig Zeit: Bis zum Termin bleibt nur ein Lerntag. Er enthält den ganzen offenen "
                         "Stoff und ist zugleich Wiederholung.")
    elif offen and not rest and plan.termin >= heute:
        warnungen.append("Bis zum Termin gibt es keinen Lerntag mehr.")
    if volle:
        warnungen.append(("Sehr voller Tag: " if len(volle) == 1 else "Sehr volle Tage: ")
                         + ", ".join(_datum_text(d) for d in volle) + ".")

    return {
        "id": plan.id, "name": plan.name, "start": plan.start.isoformat(), "termin": plan.termin.isoformat(),
        "wochentage": list(plan.wochentage), "projekte": list(plan.projekte),
        "ausgenommen": [a.model_dump() for a in plan.ausgenommen],
        "tage": tage,
        "fortschritt": {"erledigt": erl, "gesamt": len(stuecke),
                        "wiederholung_erledigt": wdh_erl, "wiederholung_gesamt": wdh_gesamt},
        "ueberfaellig": ueberfaellig,
        "unverteilt": unverteilt,
        "hinweise": hinweise,
        "warnungen": warnungen,
        "fertig": not offen and wdh_erl == wdh_gesamt,
        "archiv": plan.termin < heute,
    }


# ---------------------------------------------------------------- Speicherschicht (T007)

_ID = re.compile(r"^lp-[0-9a-f]{8}$")
_sperre = threading.Lock()


def _ordner():
    return projekte_ordner() / ".lernplaene"


def _pfad(id: str):
    if not isinstance(id, str) or not _ID.fullmatch(id):
        raise ValueError("Ungültige Plan-Kennung.")
    return _ordner() / f"{id}.json"


def _lesen(pfad) -> Lernplan | None:
    try:
        return Lernplan.model_validate_json(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # ValidationError ist ein ValueError
        return None


def speichern(plan: Lernplan) -> None:
    """Schreibt den Plan atomar nach .lernplaene/<id>.json (legt den Ordner an)."""
    pfad = _pfad(plan.id)
    with _sperre:
        atomar_schreiben(pfad, plan.model_dump_json(indent=2))


def laden(id: str) -> Lernplan | None:
    """Der Plan oder None (unbekannt, kaputte Datei oder ungültige Kennung)."""
    if not isinstance(id, str) or not _ID.fullmatch(id):
        return None
    with _sperre:
        return _lesen(_pfad(id))


def alle() -> list[Lernplan]:
    """Alle lesbaren Pläne, älteste zuerst (kaputte Dateien werden übersprungen)."""
    ordner = _ordner()
    with _sperre:
        if not ordner.is_dir():
            return []
        plaene = [p for d in sorted(ordner.glob("lp-*.json")) if _ID.fullmatch(d.stem) and (p := _lesen(d))]
    return sorted(plaene, key=lambda p: (p.erstellt, p.id))


def loeschen(id: str) -> bool:
    """Löscht den Plan. True, wenn es ihn gab."""
    if not isinstance(id, str) or not _ID.fullmatch(id):
        return False
    with _sperre:
        try:
            _pfad(id).unlink()
        except FileNotFoundError:
            return False
    return True


def _projekt_daten(slug: str) -> Projektdaten | None:
    try:
        p = Projekt.laden(slug)
        if not p.hat_inhalt():
            return None
        return projektdaten(p.meta().name, p.inhalt())
    except (FileNotFoundError, OSError, ValueError):
        return None


def lasten_der_projekte(slugs: Sequence[str], ausgenommen: Iterable = ()) -> dict[Schluessel, list[float]]:
    """`lasten` aus den gespeicherten Projekten (Reihenfolge wie `slugs`, ohne ausgenommene Themen).
    Unbekannte oder kaputte Projekte werden übersprungen."""
    return lasten_aus({s: _projekt_daten(s) for s in slugs}, slugs, ausgenommen)


def anlegen(daten: Mapping) -> Lernplan:
    """Legt einen Plan an (Erstverteilung) und speichert ihn. Bei ungültigen Angaben `ValueError`
    mit deutscher Meldung (Routen: 400); es wird dann nichts gespeichert.

    `daten`: name, projekte, termin (Datum oder JJJJ-MM-TT), wochentage, optional start (Standard heute),
    ausgenommen (Liste von {projekt, thema_id})."""
    jetzt = heute()
    name = str(daten.get("name") or "").strip()
    if not name:
        raise ValueError("Der Name darf nicht leer sein.")
    if len(name) > 60:
        raise ValueError("Der Name darf höchstens 60 Zeichen lang sein.")

    def datum(wert, was: str, standard: date | None = None) -> date:
        if wert in (None, "") and standard:
            return standard
        if isinstance(wert, date):
            return wert
        try:
            return date.fromisoformat(str(wert))
        except ValueError:
            raise ValueError(f"{was} ist kein gültiges Datum (JJJJ-MM-TT).") from None

    termin = datum(daten.get("termin"), "Der Prüfungstermin")
    start = datum(daten.get("start"), "Das Startdatum", jetzt)
    if termin <= jetzt:
        raise ValueError("Der Prüfungstermin muss in der Zukunft liegen.")
    if start >= termin:
        raise ValueError("Das Startdatum muss vor dem Prüfungstermin liegen.")

    wt = daten.get("wochentage")
    if not isinstance(wt, (list, tuple)) or not wt:
        raise ValueError("Wähle mindestens einen Wochentag.")
    if any(isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 6 for d in wt) or len(set(wt)) != len(wt):
        raise ValueError("Die Wochentage müssen verschiedene Zahlen von 0 (Montag) bis 6 (Sonntag) sein.")

    slugs = list(dict.fromkeys(daten.get("projekte") or []))
    if not slugs:
        raise ValueError("Wähle mindestens ein Projekt.")
    for slug in slugs:
        d = _projekt_daten(slug) if isinstance(slug, str) else None
        if d is None or not d["themen"]:
            raise ValueError(f"Das Projekt „{slug}“ gibt es nicht oder es hat noch keinen Inhalt.")

    try:
        ausgenommen = [a if isinstance(a, Themenverweis) else Themenverweis.model_validate(a)
                       for a in daten.get("ausgenommen") or []]
    except ValidationError:
        raise ValueError("Die ausgenommenen Themen sind ungültig.") from None
    lasten = lasten_der_projekte(slugs, ausgenommen)
    if not lasten:
        raise ValueError("Alle Themen sind ausgenommen. Wähle mindestens ein Thema.")

    for _ in range(100):
        neue_id = f"lp-{uuid.uuid4().hex[:8]}"
        if not _pfad(neue_id).exists():
            break
    try:
        plan = Lernplan(id=neue_id, name=name, start=start, termin=termin, wochentage=list(wt), projekte=slugs,
                        ausgenommen=ausgenommen, erstellt=datetime.now().replace(microsecond=0))
    except ValidationError as e:
        raise ValueError(f"Ungültige Angaben: {e.errors()[0]['msg']}") from None
    plan = neu_verteilen(plan, lasten, jetzt)  # KeinLerntag (ValueError) mit deutscher Meldung
    speichern(plan)
    return plan


def erledigt_setzen(plan: Lernplan, ziel: Mapping, wert: bool) -> Lernplan:
    """Hakt ein Stück oder einen Wiederholungstag ab (`wert=True`) oder nimmt den Haken zurück.

    `ziel`: `{projekt, thema_id, von, bis}` (ein Stück aus `plan.zuordnung`) oder `{wiederholung: Datum}`
    (Datum oder JJJJ-MM-TT; muss ein Lerntag des Plans sein). Sonst `ValueError` mit deutscher Meldung
    (Routen: 400). Wiederholtes Setzen ist harmlos. Gibt einen neuen Plan zurück, speichert nicht."""
    if "wiederholung" in ziel:
        roh = ziel["wiederholung"]
        try:
            tag = roh if isinstance(roh, date) else date.fromisoformat(str(roh))
        except ValueError:
            raise ValueError("Das Datum ist ungültig (JJJJ-MM-TT).") from None
        if tag not in lerntage(plan.start, plan.termin, plan.wochentage, plan.start):
            raise ValueError("Dieser Tag ist kein Lerntag des Plans.")
        rest = [d for d in plan.wiederholung_erledigt if d != tag]
        return plan.model_copy(update={"wiederholung_erledigt": sorted(rest + [tag]) if wert else rest})

    try:
        projekt, thema_id = ziel["projekt"], ziel["thema_id"]
        von, bis = ziel["von"], ziel["bis"]
    except KeyError:
        raise ValueError("Angaben unvollständig: projekt, thema_id, von und bis oder wiederholung.") from None
    if isinstance(von, bool) or isinstance(bis, bool) or not isinstance(von, int) or not isinstance(bis, int):
        raise ValueError("von und bis müssen ganze Zahlen sein.")
    stueck = next((z for z in plan.zuordnung
                   if (z.projekt, z.thema_id, z.von, z.bis) == (projekt, thema_id, von, bis)), None)
    if stueck is None:
        raise ValueError("Dieses Thema steht nicht im Plan.")
    rest = [e for e in plan.erledigt if (e.projekt, e.thema_id, e.von, e.bis) != (projekt, thema_id, von, bis)]
    if wert:
        rest.append(Erledigt(projekt=projekt, thema_id=thema_id, von=von, bis=bis))
    return plan.model_copy(update={"erledigt": rest})


def aendern(id: str, daten: Mapping) -> Lernplan | None:
    """Ändert einen Plan (beliebige Felder von `anlegen`: name, projekte, termin, wochentage, start, ausgenommen),
    verteilt den offenen Teil neu (Erledigtes bleibt) und speichert. None, wenn es den Plan nicht gibt.
    Prüfungen wie beim Anlegen; sonst `ValueError` mit deutscher Meldung (Routen: 400), die Datei bleibt dann
    unverändert. Ändert sich nur der Name, wird nicht neu verteilt (`neu_verteilen` wirft bei einem Termin in
    der Vergangenheit immer `KeinLerntag`)."""
    plan = laden(id)
    if plan is None:
        return None
    jetzt = heute()
    update: dict = {}

    if "name" in daten:
        name = str(daten.get("name") or "").strip()
        if not name:
            raise ValueError("Der Name darf nicht leer sein.")
        if len(name) > 60:
            raise ValueError("Der Name darf höchstens 60 Zeichen lang sein.")
        update["name"] = name

    def datum(wert, was: str) -> date:
        if isinstance(wert, date):
            return wert
        try:
            return date.fromisoformat(str(wert))
        except ValueError:
            raise ValueError(f"{was} ist kein gültiges Datum (JJJJ-MM-TT).") from None

    termin, start = plan.termin, plan.start
    if "termin" in daten:
        termin = datum(daten["termin"], "Der Prüfungstermin")
        if termin != plan.termin and termin <= jetzt:
            raise ValueError("Der Prüfungstermin muss in der Zukunft liegen.")
        update["termin"] = termin
    if "start" in daten:
        start = jetzt if daten["start"] in (None, "") else datum(daten["start"], "Das Startdatum")
        update["start"] = start
    if start >= termin:
        raise ValueError("Das Startdatum muss vor dem Prüfungstermin liegen.")

    if "wochentage" in daten:
        wt = daten["wochentage"]
        if not isinstance(wt, (list, tuple)) or not wt:
            raise ValueError("Wähle mindestens einen Wochentag.")
        if any(isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 6 for d in wt) \
                or len(set(wt)) != len(wt):
            raise ValueError("Die Wochentage müssen verschiedene Zahlen von 0 (Montag) bis 6 (Sonntag) sein.")
        update["wochentage"] = list(wt)

    slugs = list(plan.projekte)
    if "projekte" in daten:
        slugs = list(dict.fromkeys(daten.get("projekte") or []))
        if not slugs:
            raise ValueError("Wähle mindestens ein Projekt.")
        for slug in slugs:
            d = _projekt_daten(slug) if isinstance(slug, str) else None
            if d is None or not d["themen"]:
                raise ValueError(f"Das Projekt „{slug}“ gibt es nicht oder es hat noch keinen Inhalt.")
        update["projekte"] = slugs

    ausgenommen = list(plan.ausgenommen)
    if "ausgenommen" in daten:
        try:
            ausgenommen = [a if isinstance(a, Themenverweis) else Themenverweis.model_validate(a)
                           for a in daten.get("ausgenommen") or []]
        except ValidationError:
            raise ValueError("Die ausgenommenen Themen sind ungültig.") from None
    ausgenommen = [a for a in ausgenommen if a.projekt in slugs]  # Verweise auf entfernte Projekte fallen weg
    update["ausgenommen"] = ausgenommen

    try:
        neu = Lernplan.model_validate({**plan.model_dump(), **update})
    except ValidationError as e:
        raise ValueError(f"Ungültige Angaben: {e.errors()[0]['msg']}") from None

    verteilung = ("termin", "start", "wochentage", "projekte", "ausgenommen")
    if any(getattr(neu, f) != getattr(plan, f) for f in verteilung):
        lasten = lasten_der_projekte(slugs, ausgenommen)
        if not lasten:
            raise ValueError("Alle Themen sind ausgenommen. Wähle mindestens ein Thema.")
        neu = neu_verteilen(neu, lasten, jetzt)  # KeinLerntag (ValueError) mit deutscher Meldung
    if neu != plan:
        speichern(neu)
    return neu
