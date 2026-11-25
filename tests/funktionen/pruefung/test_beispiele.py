"""Die Beispiele in prompts/beispiele/ bestehen Schema und Regeln (T005) – sonst lernt das Modell Falsches."""
import json
from pathlib import Path

import pytest

from genut.funktionen.pruefung import logik
from genut.funktionen.pruefung.schema import Pruefungsbewertung, PruefungsPlan, Pruefungszug
from genut.schema import ki_schema

ORDNER = Path(logik.__file__).parent / "prompts" / "beispiele"


def laden(name: str) -> dict:
    return json.loads((ORDNER / name).read_text(encoding="utf-8"))


def test_alle_vier_beispiele_vorhanden():
    assert sorted(p.name for p in ORDNER.glob("*.json")) == [
        "bewertung.json", "plan.json", "zug_nachfrage.json", "zug_weiter.json"]


@pytest.mark.parametrize("name,modell", [("plan.json", PruefungsPlan), ("zug_nachfrage.json", Pruefungszug),
                                         ("zug_weiter.json", Pruefungszug), ("bewertung.json", Pruefungsbewertung)])
def test_beispiel_besteht_schema(name, modell):
    daten = laden(name)
    modell.model_validate(daten)
    assert set(daten) <= set(ki_schema(modell)["properties"])


def test_plan_beispiel_besteht_regeln():
    plan = PruefungsPlan.model_validate(laden("plan.json"))
    themen = sorted({f.thema_id for f in plan.fragen})
    assert logik.plan_fehler(plan, themen, len(plan.fragen)) == []
    assert logik.plan_fehler(plan, themen, len(plan.fragen) - 1)  # Gegenprobe: zu viele Fragen


def test_zug_beispiele_zeigen_die_beiden_aktionen():
    n, w = (Pruefungszug.model_validate(laden(x)) for x in ("zug_nachfrage.json", "zug_weiter.json"))
    assert n.aktion == "nachfrage" and n.text and n.punkte is None
    assert w.aktion == "weiter" and w.text is None and w.punkte in (0, 1, 2)


def test_bewertung_beispiel_besteht_regeln():
    plan = PruefungsPlan.model_validate(laden("plan.json"))
    themen = sorted({f.thema_id for f in plan.fragen})
    b = Pruefungsbewertung.model_validate(laden("bewertung.json"))
    nrs = list(range(1, len(plan.fragen) + 1))
    assert logik.bewertung_fehler(b, themen, nrs) == []
    assert logik.bewertung_fehler(b, themen, nrs[:-1])  # Gegenprobe: nr nicht beantwortet
    assert {lu.thema_id for lu in b.luecken} <= set(themen)
