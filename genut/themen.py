"""Umfang (Last) eines Themas, gemeinsam für Lernplaner (Feature 004) und Prüfung (Feature 005).

Ein Thema besteht aus Einheiten in fester Reihenfolge: jeder Block, jede Aufgabe, alle Quizfragen des
Themas als eine Einheit, alle Karten des Themas als eine Einheit (specs/004-lernplaner/research.md Punkt 1 und 2).
"""
from __future__ import annotations

from .schema import Dokument, Thema

GEWICHT_BLOCK = 1
GEWICHT_AUFGABE = 2
GEWICHT_QUIZ = 0.5
GEWICHT_KARTE = 0.25


def einheiten(thema: Thema, doc: Dokument) -> list[float]:
    """Lasten der Einheiten des Themas in fester Reihenfolge: Blöcke, Aufgaben, Quiz gesamt, Karten gesamt.

    Ein Thema ohne jeden Inhalt ergibt eine leere Liste (der Lernplaner zählt es als eine Einheit der Last 1).
    """
    lasten: list[float] = [float(GEWICHT_BLOCK)] * len(thema.bloecke)
    lasten += [float(GEWICHT_AUFGABE) for a in doc.aufgaben if a.thema_id == thema.id]
    quiz = sum(1 for f in doc.quiz if f.thema_id == thema.id)
    if quiz:
        lasten.append(quiz * GEWICHT_QUIZ)
    karten = sum(1 for k in doc.karten if k.thema_id == thema.id)
    if karten:
        lasten.append(karten * GEWICHT_KARTE)
    return lasten


def last(thema: Thema, doc: Dokument) -> float:
    """Last = Blöcke × 1 + Aufgaben × 2 + Quizfragen × 0,5 + Karten × 0,25, mindestens 1."""
    return max(1.0, sum(einheiten(thema, doc)))
