"""Tests der Lernplan-Logik (reine Funktionen): Lerntage, Teilen, Verteilen, Neu verteilen, Plan-Antwort."""
import random
import time
from datetime import date, datetime, timedelta

import pytest

from genut.funktionen.lernplan import logik as L
from genut.funktionen.lernplan.schema import Erledigt, Lernplan

START = date(2026, 11, 16)  # Montag
EPS = 1e-9


def tage_ab(n, start=START):
    return [start + timedelta(days=i) for i in range(n)]


def einh_aus_lasten(lasten):
    """Jede Einheit hat Last 1."""
    return {("p", f"t{i}"): [1.0] * int(x) for i, x in enumerate(lasten)}


def tagindex(zs, tage):
    return [tage.index(z.datum) for z in zs]


def neuer_plan(start=START, termin=None, wt=(0, 1, 2, 3, 4, 5, 6), projekte=("p",)):
    return Lernplan(id="lp-0000abcd", name="Test", start=start, termin=termin or start + timedelta(days=6),
                    wochentage=list(wt), projekte=list(projekte), erstellt=datetime(2026, 11, 15, 10, 0))


def erstverteilung(einh, start, termin, wt=(0, 1, 2, 3, 4, 5, 6)):
    return L.neu_verteilen(neuer_plan(start, termin, wt), einh, start)


def als_erledigt(zs):
    return [Erledigt(projekt=z.projekt, thema_id=z.thema_id, von=z.von, bis=z.bis) for z in zs]


def projekt_daten(einh, name="P"):
    return {"p": {"name": name, "themen": [{"id": k[1], "titel": k[1].upper(), "einheiten": v}
                                           for k, v in einh.items()]}}


# ------------------------------------------------------------ Lerntage

def test_lerntage_wochentage_und_prueftag():
    # Mo 16.11. bis Mi 25.11. (Prüfungstag), nur Mo, Mi, Fr
    tage = L.lerntage(date(2026, 11, 16), date(2026, 11, 25), [0, 2, 4], date(2026, 11, 1))
    assert tage == [date(2026, 11, 16), date(2026, 11, 18), date(2026, 11, 20), date(2026, 11, 23)]
    # der Prüfungstag zählt nie, auch wenn sein Wochentag gewählt ist
    assert date(2026, 11, 25) not in tage and date(2026, 11, 25).weekday() == 2
    assert all(t.weekday() in (0, 2, 4) for t in tage)


def test_lerntage_heute_zaehlt_mit_und_start_in_zukunft():
    alle = list(range(7))
    assert L.lerntage(START, START + timedelta(days=5), alle, START + timedelta(days=2))[0] == START + timedelta(days=2)
    assert L.lerntage(START + timedelta(days=3), START + timedelta(days=6), alle, START)[0] == START + timedelta(days=3)
    # heute = Prüfungstag oder später: keine Lerntage
    assert L.lerntage(START, START + timedelta(days=3), alle, START + timedelta(days=3)) == []


def test_lerntage_keine_gewaehlten_wochentage_im_zeitraum():
    # nur Samstag/Sonntag gewählt, Zeitraum Mo-Fr
    assert L.lerntage(START, START + timedelta(days=5), [5, 6], START) == []


def test_ein_lerntag_gibt_warnung_und_alle_themen():
    einh = einh_aus_lasten([2, 3, 1])
    p = erstverteilung(einh, START, START + timedelta(days=1))
    assert len(p.zuordnung) == 3 and {z.datum for z in p.zuordnung} == {START}
    a = L.plan_antwort(p, projekt_daten(einh), START)
    assert any("Sehr wenig Zeit" in w for w in a["warnungen"])
    assert len(a["tage"]) == 1 and a["tage"][0]["wiederholung"]


def test_kein_lerntag_fehler_und_plan_unveraendert():
    einh = einh_aus_lasten([5, 5])
    with pytest.raises(L.KeinLerntag):
        erstverteilung(einh, START, START + timedelta(days=3), wt=[6])  # nur Sonntag, Zeitraum Mo-Mi
    with pytest.raises(L.KeinLerntag):
        L.verteilen([], [])
    p = erstverteilung(einh, START, START + timedelta(days=6))
    vorher = p.model_dump()
    with pytest.raises(L.KeinLerntag):
        L.neu_verteilen(p, einh, START + timedelta(days=6))  # heute = Prüfungstag
    assert p.model_dump() == vorher


def test_heute_ist_ersetzbar(monkeypatch):
    assert L.heute() == date.today()
    monkeypatch.setattr(L, "heute", lambda: date(2026, 1, 2))
    assert L.heute() == date(2026, 1, 2)


# ------------------------------------------------------------ feste Verteilungsbeispiele

def test_beispiel_10_90_10_luecke_geschlossen():
    tage = tage_ab(5)  # 4 Lerntage + Wiederholungstag
    st = L.teilen(einh_aus_lasten([10, 90, 10]), 4)
    zs = L.verteilen(st, tage)
    zweites = [z for z in zs if z.thema_id == "t1"]
    assert [s.last for s in st if s.thema_id == "t1"] == [30, 30, 30]
    assert len(zweites) == 3 and [z.teile for z in zweites] == [3, 3, 3]
    # ohne „Lücken schließen“ lägen sie auf 0, 2, 3; mit auf aufeinanderfolgenden Tagen
    idx = tagindex(zweites, tage)
    assert idx == [idx[0], idx[0] + 1, idx[0] + 2]
    assert tagindex(zs, tage) == sorted(tagindex(zs, tage)) and tagindex(zs, tage)[0] == 0


@pytest.mark.parametrize("n", [6, 7])
def test_beispiel_20_2_2_2_erstes_thema_in_aufeinanderfolgenden_teilen(n):
    tage = tage_ab(n)
    zs = L.verteilen(L.teilen(einh_aus_lasten([20, 2, 2, 2]), n - 1), tage)
    erstes = [z for z in zs if z.thema_id == "t0"]
    assert len(erstes) > 1
    idx = tagindex(erstes, tage)
    assert idx == list(range(idx[0], idx[0] + len(idx))) and idx[0] == 0
    # D >= N' : danach die kleinen Themen, jedes unter 1,5 Ø ungeteilt
    assert all(z.teile == 1 for z in zs if z.thema_id != "t0")


def test_erster_lerntag_hat_thema_bei_sehr_grossem_erstem_thema():
    for einh in (einh_aus_lasten([50, 1, 1, 1, 1, 1]),
                 {("p", "a"): [50.0], **{("p", f"b{i}"): [1.0] for i in range(5)}}):
        tage = tage_ab(5)
        zs = L.verteilen(L.teilen(einh, 4), tage)
        assert tagindex(zs, tage)[0] == 0
        assert tagindex(zs, tage) == sorted(tagindex(zs, tage))
        assert all(i < 4 for i in tagindex(zs, tage))


def test_teilen_ohne_themen_und_leeres_thema():
    assert L.teilen({}, 3) == []
    st = L.teilen({("p", "leer"): []}, 3)
    assert len(st) == 1 and st[0].last == 1 and (st[0].von, st[0].bis) == (0, 1)


# ------------------------------------------------------------ Eigenschaftstests

def zufall_themen(rng):
    n = rng.randint(1, 25)
    einh = {}
    for i in range(n):
        m = rng.choice([1, 1, 2, 3, 5, 10, 20, 40])
        einh[("p", f"t{i}")] = [rng.choice([1.0, 1.0, 1.0, 2.0, 0.5, 0.25, 3.0, 1.5])
                                for _ in range(rng.randint(0, m))]
    return einh


def pruefe_verteilung(einh, tage):
    """Gibt eine Liste von Fehlermeldungen zurück (leer = alles in Ordnung)."""
    fehler = []
    D = len(tage) - 1
    st = L.teilen(einh, D)
    zs = L.verteilen(st, tage)
    oe = L.bezugslast(einh, D)
    gross = max(max(e or [1.0]) for e in einh.values())
    T = sum(s.last for s in st)

    for s in st:  # Stückgrenze vor dem Zusammenlegen
        if s.last > max(1.5 * oe, oe + gross) + EPS:
            fehler.append(f"Stück zu groß {s}")
    for k, e in einh.items():
        if max(1, sum(e)) <= 1.5 * oe and len([s for s in st if s.schluessel == k]) > 1:
            fehler.append(f"unnötig geteilt {k}")
        n = max(1, len(e))
        teile = [z for z in zs if (z.projekt, z.thema_id) == k]
        pos = 0
        for v, b in sorted((z.von, z.bis) for z in teile):  # lückenlos, ohne Überschneidung
            if v != pos:
                fehler.append(f"Bereiche {k}")
            pos = b
        if pos != n:
            fehler.append(f"Einheiten nicht abgedeckt {k}")
        if [z.teil for z in teile] != list(range(1, len(teile) + 1)) or any(z.teile != len(teile) for z in teile):
            fehler.append(f"Nummerierung {k}")
        idx = [tage.index(z.datum) for z in teile]
        if any(b != a + 1 for a, b in zip(idx, idx[1:])):
            fehler.append(f"Teile nicht aufeinanderfolgend {k} {idx}")
    idx = tagindex(zs, tage)
    if idx != sorted(idx):
        fehler.append("Reihenfolge")
    if any(z.datum not in tage for z in zs):
        fehler.append("Tag außerhalb")
    if len(tage) >= 2:
        if any(i == len(tage) - 1 for i in idx):
            fehler.append("Thema am Wiederholungstag")
        if idx[0] != 0:
            fehler.append("erster Tag leer")
        last_tag = {}
        for z in zs:
            last_tag[z.datum] = last_tag.get(z.datum, 0) + L.bereich_last(einh[(z.projekt, z.thema_id)], z.von, z.bis)
        if max(last_tag.values()) > T / D + max(s.last for s in st) + EPS:
            fehler.append("Lastgrenze")
    else:
        if any(i != 0 for i in idx) or len(zs) != len(einh):
            fehler.append("ein Lerntag: nicht alle Themen am Tag")
    return fehler


def test_eigenschaften_verteilen_zufall():
    rng = random.Random(4711)
    for lauf in range(6000):
        einh = zufall_themen(rng)
        tage = tage_ab(rng.randint(1, 30))
        fehler = pruefe_verteilung(einh, tage)
        assert not fehler, f"Lauf {lauf}: {fehler[:3]} ({len(einh)} Themen, {len(tage)} Tage)"


def test_eigenschaften_nur_gewaehlte_wochentage_und_vor_dem_termin():
    rng = random.Random(99)
    for lauf in range(5000):
        einh = zufall_themen(rng)
        wt = sorted(rng.sample(range(7), rng.randint(1, 7)))
        termin = START + timedelta(days=rng.randint(1, 40))
        try:
            p = erstverteilung(einh, START, termin, wt)
        except L.KeinLerntag:
            assert not L.lerntage(START, termin, wt, START)
            continue
        assert all(z.datum.weekday() in wt and START <= z.datum < termin for z in p.zuordnung), lauf
        assert [z.datum for z in p.zuordnung] == sorted(z.datum for z in p.zuordnung)


# ------------------------------------------------------------ neu_verteilen

def test_neu_verteilen_nummeriert_nach_erledigtem_teil_weiter():
    einh = einh_aus_lasten([30, 2, 2])
    p = erstverteilung(einh, START, START + timedelta(days=8))
    erstes = [z for z in p.zuordnung if z.thema_id == "t0"]
    assert len(erstes) == 3 and [z.teil for z in erstes] == [1, 2, 3]
    z1 = erstes[0]
    p2 = p.model_copy(update={"erledigt": als_erledigt([z1])})
    p3 = L.neu_verteilen(p2, einh, START + timedelta(days=2))
    t0 = [z for z in p3.zuordnung if z.thema_id == "t0"]
    assert (t0[0].datum, t0[0].von, t0[0].bis, t0[0].teil) == (z1.datum, z1.von, z1.bis, 1)  # erledigt, unverändert
    assert [z.teil for z in t0] == list(range(1, len(t0) + 1)) and all(z.teile == len(t0) for z in t0)
    assert len(t0) >= 2 and all(z.datum >= START + timedelta(days=2) for z in t0[1:])
    assert [(z.von, z.bis) for z in t0][0] == (z1.von, z1.bis)
    assert t0[1].von == z1.bis and t0[-1].bis == 30
    # Plan-Antwort zeigt 2/n, 3/n
    a = L.plan_antwort(p3, projekt_daten(einh), START + timedelta(days=2))
    teile = [(s["teil"], s["teile"]) for t in a["tage"] for s in t["themen"] if s["thema_id"] == "t0"]
    assert teile[1][0] == 2


def test_neu_verteilen_merkt_urspruengliches_datum():
    einh = einh_aus_lasten([3, 3, 3, 3])
    p = erstverteilung(einh, START, START + timedelta(days=8))
    heute = START + timedelta(days=3)
    q = L.neu_verteilen(p, einh, heute)
    verschoben = [z for z in q.zuordnung if z.urspruenglich]
    assert verschoben and all(z.urspruenglich != z.datum and z.datum >= heute for z in verschoben)


def test_neu_verteilen_deterministisch_und_erledigtes_unveraendert():
    rng = random.Random(2024)
    geprueft = 0
    for lauf in range(3000):
        einh = {("p", f"t{i}"): [1.0] * rng.randint(0, rng.choice([2, 5, 20])) for i in range(rng.randint(1, 12))}
        n = rng.randint(2, 25)
        wt = sorted(rng.sample(range(7), rng.randint(1, 7)))
        try:
            p = erstverteilung(einh, START, START + timedelta(days=n), wt)
        except L.KeinLerntag:
            continue
        wahl = [z for z in p.zuordnung if rng.random() < 0.4]
        p = p.model_copy(update={"erledigt": als_erledigt(wahl)})
        heute = START + timedelta(days=rng.randint(0, n))
        try:
            q = L.neu_verteilen(p, einh, heute)
        except L.KeinLerntag:
            assert not L.lerntage(p.start, p.termin, p.wochentage, heute)
            continue
        geprueft += 1
        assert q == L.neu_verteilen(p, einh, heute), lauf  # deterministisch
        erl = {(e.projekt, e.thema_id, e.von, e.bis) for e in q.erledigt}
        assert {(z.thema_id, z.von, z.bis, z.datum) for z in wahl} == \
               {(z.thema_id, z.von, z.bis, z.datum) for z in q.zuordnung if (z.projekt, z.thema_id, z.von, z.bis) in erl}, lauf
        for z in q.zuordnung:  # offene Stücke nie in der Vergangenheit, nur Lerntage
            if (z.projekt, z.thema_id, z.von, z.bis) not in erl:
                assert z.datum >= heute and z.datum.weekday() in wt, lauf
        for k, e in einh.items():  # jede Einheit genau einmal, Nummerierung lückenlos
            teile = sorted((z for z in q.zuordnung if (z.projekt, z.thema_id) == k), key=lambda z: z.von)
            pos = 0
            for z in teile:
                assert z.von == pos, (lauf, k)
                pos = z.bis
            assert pos == max(1, len(e)), (lauf, k)
            assert sorted(z.teil for z in teile) == list(range(1, len(teile) + 1))
            assert all(z.teile == len(teile) for z in teile)
    assert geprueft > 1000


def test_leer_gewordene_vergangene_tage_sind_keine_wiederholung_und_fertig_bleibt_erreichbar():
    rng = random.Random(7)
    geprueft = 0
    for lauf in range(1500):
        einh = {("p", f"t{i}"): [1.0] * rng.randint(0, rng.choice([2, 5, 20])) for i in range(rng.randint(1, 12))}
        n = rng.randint(2, 25)
        wt = sorted(rng.sample(range(7), rng.randint(1, 7)))
        try:
            p = erstverteilung(einh, START, START + timedelta(days=n), wt)
        except L.KeinLerntag:
            continue
        wahl = [z for z in p.zuordnung if rng.random() < 0.4]
        p = p.model_copy(update={"erledigt": als_erledigt(wahl)})
        heute = START + timedelta(days=rng.randint(0, n))
        try:
            q = L.neu_verteilen(p, einh, heute)
        except L.KeinLerntag:
            continue
        geprueft += 1
        proj = projekt_daten(einh)
        alle = q.model_copy(update={"erledigt": als_erledigt(q.zuordnung)})
        a = L.plan_antwort(alle, proj, heute)
        wdh = [date.fromisoformat(t["datum"]) for t in a["tage"] if t["wiederholung"]]
        alle = alle.model_copy(update={"wiederholung_erledigt": wdh})
        a = L.plan_antwort(alle, proj, heute)
        assert a["fertig"], (lauf, a["fortschritt"])
        for t in a["tage"]:
            d = date.fromisoformat(t["datum"])
            if d < heute and not t["themen"] and d not in wdh:
                assert not t["wiederholung"], lauf
    assert geprueft > 500


def test_vergangener_leerer_tag_ist_frei_im_verlauf():
    einh = einh_aus_lasten([2, 2])
    p = erstverteilung(einh, START, START + timedelta(days=6))
    heute = START + timedelta(days=3)
    q = L.neu_verteilen(p, einh, heute)  # nichts erledigt: alles ab heute
    a = L.plan_antwort(q, projekt_daten(einh), heute)
    for t in a["tage"]:
        if date.fromisoformat(t["datum"]) < heute:
            assert not t["themen"] and not t["wiederholung"]


def test_plan_antwort_grundform():
    einh = einh_aus_lasten([4, 4, 4])
    p = erstverteilung(einh, START, START + timedelta(days=6))
    a = L.plan_antwort(p, projekt_daten(einh), START)
    assert a["fortschritt"]["gesamt"] == 3 and a["fortschritt"]["erledigt"] == 0
    assert not a["fertig"] and not a["archiv"] and a["ueberfaellig"] == 0
    assert a["tage"][0]["themen"][0]["link"] == "#/p/p/vorschau/t0"
    assert a["tage"][-1]["wiederholung"]
    a2 = L.plan_antwort(p, projekt_daten(einh), START + timedelta(days=3))
    assert a2["ueberfaellig"] >= 1


# ------------------------------------------------------------ Laufzeit (SC-005)

def test_150_themen_unter_einer_sekunde():
    rng = random.Random(150)
    einh = {("p", f"t{i}"): [rng.choice([1.0, 2.0, 0.5, 0.25]) for _ in range(rng.randint(1, 30))]
            for i in range(150)}
    proj = projekt_daten(einh)
    for tage_n in (10, 60, 400):
        t0 = time.perf_counter()
        p = erstverteilung(einh, START, START + timedelta(days=tage_n))
        a = L.plan_antwort(p, proj, START)
        dauer = time.perf_counter() - t0
        assert dauer < 1.0, (tage_n, dauer)
        assert a["fortschritt"]["gesamt"] >= 150
