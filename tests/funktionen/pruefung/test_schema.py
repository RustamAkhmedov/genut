import json

import pytest
from pydantic import ValidationError

from genut.funktionen.pruefung.schema import (Nachricht, PlanFrage, Pruefung, Pruefungsbewertung,
                                              PruefungsPlan, Pruefungszug, PunkteEintrag)
from genut.schema import ki_schema

PR = dict(id="pr-3f9a1c2e", erstellt="2026-11-15T10:12:00", themen=["t-1"])


@pytest.mark.parametrize("m", [PruefungsPlan, Pruefungszug, Pruefungsbewertung])
def test_ki_schema(m):
    s = ki_schema(m)
    text = json.dumps(s)
    assert "$defs" in s or s["type"] == "object"
    for serverfeld in ('"plan"', '"verlauf"', '"schema_version"', '"link"'):
        assert serverfeld not in text
    assert "minimum" not in text and "pattern" not in text


def test_zug_felder():
    assert set(ki_schema(Pruefungszug)["properties"]) == {"aktion", "text", "punkte", "anmerkung"}


def test_zug_regeln():
    Pruefungszug(aktion="nachfrage", text="Warum?")
    Pruefungszug(aktion="weiter", punkte=2)
    for kw in [dict(aktion="nachfrage"), dict(aktion="nachfrage", text="x", punkte=1),
               dict(aktion="weiter"), dict(aktion="weiter", punkte=1, text="x"),
               dict(aktion="weiter", punkte=3), dict(aktion="weiter", punkte=-1),
               dict(aktion="egal", punkte=1), dict(aktion="weiter", punkte=1, extra=1)]:
        with pytest.raises(ValidationError):
            Pruefungszug(**kw)


def test_plan_grenzen():
    PlanFrage(thema_id="t", frage="?", erwartung=["a", "b"])
    for e in (["a"], ["a"] * 7):
        with pytest.raises(ValidationError):
            PlanFrage(thema_id="t", frage="?", erwartung=e)
    with pytest.raises(ValidationError):
        PruefungsPlan(fragen=[PlanFrage(thema_id="t", frage="?", erwartung=["a", "b"])] * 13)


def test_bewertung_max_5_luecken():
    luecken = [dict(thema_id="t", hinweis="h")] * 6
    with pytest.raises(ValidationError):
        Pruefungsbewertung(begruendung="b", luecken=luecken, rueckmeldungen=[])


@pytest.mark.parametrize("n,ok", [(2, False), (3, True), (12, True), (13, False)])
def test_fragen_anzahl(n, ok):
    if ok:
        assert Pruefung(**PR, fragen_anzahl=n).fragen_anzahl == n
    else:
        with pytest.raises(ValidationError):
            Pruefung(**PR, fragen_anzahl=n)


@pytest.mark.parametrize("pid", ["pr-3F9A1C2E", "pr-3f9a1c2", "lp-3f9a1c2e", "pr-3f9a1c2e0"])
def test_id_ungueltig(pid):
    with pytest.raises(ValidationError):
        Pruefung(**{**PR, "id": pid})


def test_antwortlaenge():
    Nachricht(art="schueler", nr=1, text="x" * 4000, status="wartet")
    with pytest.raises(ValidationError):
        Nachricht(art="schueler", nr=1, text="x" * 4001, status="wartet")


def test_punkte_grenzen_und_eindeutig():
    for p in (0, 2):
        PunkteEintrag(nr=1, punkte=p)
    with pytest.raises(ValidationError):
        PunkteEintrag(nr=1, punkte=3)
    with pytest.raises(ValidationError):
        Pruefung(**PR, punkte=[dict(nr=1, punkte=1), dict(nr=1, punkte=2)])


def test_roundtrip():
    p = Pruefung(**PR, plan=[dict(nr=1, thema_id="t-1", frage="?", erwartung=["a", "b"])],
                 verlauf=[dict(art="pruefer", nr=1, typ="frage", text="?")])
    assert Pruefung.model_validate_json(p.model_dump_json()) == p
