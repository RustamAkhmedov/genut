import pytest
from pydantic import ValidationError

from genut.funktionen.lernplan.schema import Erledigt, Lernplan, Themenverweis, Zuordnung

BASIS = dict(id="lp-3f9a1c2e", name="Test", start="2026-11-16", termin="2026-12-09",
             wochentage=[0, 2], projekte=["a"], erstellt="2026-11-15T10:12:00")


def plan(**kw):
    return Lernplan(**{**BASIS, **kw})


def test_gueltig():
    p = plan(name="  Hallo ", zuordnung=[dict(projekt="a", thema_id="t", datum="2026-11-16",
                                              teil=1, teile=1, von=0, bis=3)])
    assert p.name == "Hallo" and p.zuordnung[0].urspruenglich is None


@pytest.mark.parametrize("kw", [
    dict(name="   "), dict(name="x" * 61), dict(wochentage=[]), dict(wochentage=[7]),
    dict(wochentage=[-1]), dict(wochentage=[1, 1]), dict(projekte=[]),
    dict(id="lp-ABCDEF12"), dict(id="lp-1234567"), dict(id="x-3f9a1c2e"),
    dict(start="2026-12-09"), dict(extra=1),
])
def test_plan_ungueltig(kw):
    with pytest.raises(ValidationError):
        plan(**kw)


def test_name_60_ok():
    assert len(plan(name="x" * 60).name) == 60


@pytest.mark.parametrize("teil,teile,von,bis", [(0, 1, 0, 1), (2, 1, 0, 1), (1, 1, 2, 2), (1, 1, 3, 2), (1, 1, -1, 2)])
def test_zuordnung_ungueltig(teil, teile, von, bis):
    with pytest.raises(ValidationError):
        Zuordnung(projekt="a", thema_id="t", datum="2026-11-16", teil=teil, teile=teile, von=von, bis=bis)


def test_erledigt_und_verweis():
    Erledigt(projekt="a", thema_id="t", von=0, bis=1)
    with pytest.raises(ValidationError):
        Erledigt(projekt="a", thema_id="t", von=1, bis=1)
    with pytest.raises(ValidationError):
        Themenverweis(projekt="a", thema_id="t", x=1)
