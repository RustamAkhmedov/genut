"""Tests von erledigt_setzen (reine Logik)."""
from datetime import date

import pytest

from genut.funktionen.lernplan import logik as L

from .test_logik import START, einh_aus_lasten, erstverteilung

TERMIN = date(2026, 11, 20)


def plan():
    return erstverteilung(einh_aus_lasten([4, 2]), START, TERMIN)


def stueck(p, i=0):
    z = p.zuordnung[i]
    return {"projekt": z.projekt, "thema_id": z.thema_id, "von": z.von, "bis": z.bis}


def test_stueck_abhaken_und_zuruecknehmen():
    p = plan()
    p2 = L.erledigt_setzen(p, stueck(p), True)
    assert len(p2.erledigt) == 1 and p.erledigt == []
    assert L.erledigt_setzen(p2, stueck(p), True).erledigt == p2.erledigt  # idempotent
    assert L.erledigt_setzen(p2, stueck(p), False).erledigt == []
    assert L.erledigt_setzen(p, stueck(p), False).erledigt == []


def test_unbekanntes_stueck():
    p = plan()
    for ziel in ({**stueck(p), "thema_id": "t-nix"}, {**stueck(p), "bis": 99}, {"projekt": "p"}):
        with pytest.raises(ValueError):
            L.erledigt_setzen(p, ziel, True)


def test_wiederholungstag():
    p = plan()
    tag = date(2026, 11, 19)
    p2 = L.erledigt_setzen(p, {"wiederholung": "2026-11-19"}, True)
    assert p2.wiederholung_erledigt == [tag]
    assert L.erledigt_setzen(p2, {"wiederholung": tag}, True).wiederholung_erledigt == [tag]
    assert L.erledigt_setzen(p2, {"wiederholung": "2026-11-19"}, False).wiederholung_erledigt == []


def test_wiederholung_ungueltig():
    p = plan()
    for d in ("kaputt", "2026-12-31", "2026-11-20"):  # Müll, außerhalb, Prüfungstag
        with pytest.raises(ValueError):
            L.erledigt_setzen(p, {"wiederholung": d}, True)
