"""Fake-Prüfer für die Tests der mündlichen Prüfung (test_ablauf, test_api, fake_server).

`FakeModell` erkennt die Aufrufart am Schema (plan, zug, bewertung) und liefert der Reihe nach vorbereitete
Antworten aus `plan`, `zug`, `bewertung`. Ein Eintrag ist ein dict (wird geliefert), eine Exception (wird
geworfen) oder eine Funktion `f(prompt) -> dict`. Ist die Liste einer Art leer, antwortet ein plausibler
Standard-Prüfer aus dem Prompt (feste Fragen je Thema, Nachfrage bei kurzer Antwort, Punkte nach Länge).

    fake = einsetzen(monkeypatch, FakeModell(zug=[{"aktion": "weiter", "text": None, "punkte": 2}]))
    ...
    assert fake.anzahl("zug") == 3
"""
from __future__ import annotations

import re

KURZ = 40  # kürzere Antworten bekommen (falls erlaubt) eine Nachfrage


def art_von(schema: dict) -> str:
    props = set(schema.get("properties", {}))
    if "fragen" in props:
        return "plan"
    if "aktion" in props:
        return "zug"
    if "begruendung" in props:
        return "bewertung"
    raise AssertionError(f"unbekanntes Schema: {sorted(props)}")


# ---------------------------------------------------------------- Standard-Prüfer (aus dem Prompt)

def standard_plan(prompt: str) -> dict:
    themen = re.findall(r"^- `(t-[^`]+)`: (.*)$", prompt, re.M)
    n = int(re.search(r"genau \*\*(\d+)\*\* Hauptfragen", prompt).group(1))
    fragen = []
    for k in range(n):
        tid, titel = themen[k % len(themen)]
        fragen.append({"thema_id": tid, "frage": f"Frage {k + 1}: Erklären Sie das Wichtigste zu „{titel}“.",
                       "erwartung": [f"Kernbegriff zu {titel}", f"Ein Beispiel zu {titel}"]})
    return {"fragen": fragen}


def antwort_aus(prompt: str) -> str:
    m = re.search(r"<antwort>\n(.*?)\n</antwort>", prompt, re.S)
    return m.group(1) if m else ""


def standard_zug(prompt: str) -> dict:
    antwort = antwort_aus(prompt)
    erlaubt = re.search(r"## Nachfrage noch erlaubt: (ja|nein)", prompt).group(1) == "ja"
    if erlaubt and len(antwort) < KURZ:
        return {"aktion": "nachfrage", "text": "Können Sie das genauer erklären?", "punkte": None,
                "anmerkung": "Antwort zu knapp."}
    punkte = 0 if antwort == "(keine Antwort)" else (2 if len(antwort) >= 2 * KURZ else 1)
    return {"aktion": "weiter", "text": None, "punkte": punkte, "anmerkung": f"Fake: {punkte} Punkte."}


def standard_bewertung(prompt: str) -> dict:
    zeilen = re.findall(r"^- Frage (\d+) · Thema `([^`]+)` · (\d) von 2 Punkten$", prompt, re.M)
    luecken, gesehen = [], set()
    for _, tid, p in zeilen:
        if int(p) < 2 and tid not in gesehen and len(luecken) < 5:
            gesehen.add(tid)
            luecken.append({"thema_id": tid, "hinweis": "Wiederholen Sie die Kernbegriffe dieses Themas."})
    return {"begruendung": "Fake-Auswertung der Übungsprüfung.", "luecken": luecken,
            "rueckmeldungen": [{"nr": int(nr), "fehlte": "Nichts Wesentliches." if p == "2" else "Details fehlten.",
                                "stoff_hinweis": "Siehe Stoff."} for nr, _, p in zeilen]}


STANDARD = {"plan": standard_plan, "zug": standard_zug, "bewertung": standard_bewertung}


# ---------------------------------------------------------------- Fake-Modell

class FakeModell:
    name = "fake"

    def __init__(self, plan=(), zug=(), bewertung=()):
        self.vorrat = {"plan": list(plan), "zug": list(zug), "bewertung": list(bewertung)}
        self.aufrufe: list[tuple[str, str]] = []  # (art, prompt)

    def json(self, prompt: str, schema: dict, bilder: list) -> dict:
        art = art_von(schema)
        self.aufrufe.append((art, prompt))
        eintrag = self.vorrat[art].pop(0) if self.vorrat[art] else STANDARD[art]
        if isinstance(eintrag, BaseException):
            raise eintrag
        return eintrag(prompt) if callable(eintrag) else eintrag

    def text(self, prompt: str, bilder: list) -> str:
        raise AssertionError("Die Prüfung ruft nie text() auf")

    def anzahl(self, art: str | None = None) -> int:
        return sum(1 for a, _ in self.aufrufe if art is None or a == art)

    def prompts(self, art: str) -> list[str]:
        return [p for a, p in self.aufrufe if a == art]


def einsetzen(monkeypatch, fake: FakeModell | None = None) -> FakeModell:
    """Ersetzt genut.funktionen.pruefung.logik.waehlen durch den Fake (nur "claude_code" erlaubt)."""
    from genut.funktionen.pruefung import logik

    fake = fake or FakeModell()

    def waehlen(name: str):
        assert name == "claude_code", name
        return fake

    monkeypatch.setattr(logik, "waehlen", waehlen)
    return fake
