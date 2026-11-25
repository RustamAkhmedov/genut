"""HTTP-Schnittstelle des Lernplaners (specs/004-lernplaner/contracts/api.md)."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from genut.config import laden
from genut.funktionen.lernplan import logik
from genut.server import app

HEUTE = date(2026, 11, 16)  # Montag


@pytest.fixture(autouse=True)
def _heute(monkeypatch):
    monkeypatch.setattr(logik, "heute", lambda: HEUTE)


@pytest.fixture
def client():
    return TestClient(app)


def body(slug, **kw):
    return {"name": "Plan", "projekte": [slug], "termin": "2026-12-09", "wochentage": [0, 2, 5], **kw}


def _config(monkeypatch, tmp_path, text):
    cfg = tmp_path / "config.toml"
    cfg.write_text(text, encoding="utf-8")
    monkeypatch.setenv("GENUT_CONFIG", str(cfg))
    laden.cache_clear()


@pytest.fixture
def config_zuruecksetzen():
    yield
    laden.cache_clear()


def test_anlegen_erfolg(client, projekt_mit_inhalt):
    r = client.post("/api/lernplaene", json=body(projekt_mit_inhalt.slug))
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["id"].startswith("lp-") and p["name"] == "Plan"
    assert p["start"] == "2026-11-16" and p["termin"] == "2026-12-09" and p["wochentage"] == [0, 2, 5]
    assert p["tage"] and all(date.fromisoformat(t["datum"]).weekday() in (0, 2, 5) for t in p["tage"])
    assert p["fortschritt"]["erledigt"] == 0 and p["fortschritt"]["gesamt"] > 0
    assert p["fertig"] is False and p["archiv"] is False and p["ueberfaellig"] == 0
    for k in ("projekte", "ausgenommen", "unverteilt", "hinweise", "warnungen"):
        assert k in p


@pytest.mark.parametrize("aender, meldung", [
    ({"name": "  "}, "Name"),
    ({"termin": "2026-11-16"}, "Zukunft"),
    ({"termin": "2026-11-01"}, "Zukunft"),
    ({"wochentage": []}, "Wochentag"),
    ({"projekte": ["gibt-es-nicht"]}, "Inhalt"),
    ({"termin": "2026-11-20", "wochentage": [5]}, "Lerntag"),
])
def test_anlegen_fehler_400(client, projekt_mit_inhalt, aender, meldung):
    r = client.post("/api/lernplaene", json={**body(projekt_mit_inhalt.slug), **aender})
    assert r.status_code == 400 and meldung in r.json()["detail"]
    assert client.get("/api/lernplaene").json() == {"aktuell": [], "archiv": []}


def test_projekt_ohne_inhalt_400(client, projekte):
    from genut.projekt import Projekt

    p = Projekt.anlegen("Leer")
    r = client.post("/api/lernplaene", json=body(p.slug))
    assert r.status_code == 400 and "Inhalt" in r.json()["detail"]


def test_alle_themen_ausgenommen_400(client, projekt_mit_inhalt):
    s = projekt_mit_inhalt.slug
    themen = client.get(f"/api/projekte/{s}/themen").json()
    aus = [{"projekt": s, "thema_id": t["id"]} for t in themen]
    r = client.post("/api/lernplaene", json=body(s, ausgenommen=aus))
    assert r.status_code == 400 and "ausgenommen" in r.json()["detail"]


def test_liste_aktuell_und_archiv(client, projekt_mit_inhalt, monkeypatch):
    s = projekt_mit_inhalt.slug
    assert client.get("/api/lernplaene").json() == {"aktuell": [], "archiv": []}
    a = client.post("/api/lernplaene", json=body(s, name="Alt", termin="2026-11-20", wochentage=[0, 1, 2, 3])).json()
    b = client.post("/api/lernplaene", json=body(s, name="Neu")).json()
    monkeypatch.setattr(logik, "heute", lambda: date(2026, 11, 25))
    liste = client.get("/api/lernplaene").json()
    assert [x["id"] for x in liste["aktuell"]] == [b["id"]]
    assert [x["id"] for x in liste["archiv"]] == [a["id"]]
    z = liste["archiv"][0]
    assert z["name"] == "Alt" and z["termin"] == "2026-11-20" and z["projekte"] == ["Test Integral"]
    for k in ("fortschritt", "ueberfaellig", "fertig"):
        assert k in z


def test_plan_lesen_404(client, projekt_mit_inhalt):
    p = client.post("/api/lernplaene", json=body(projekt_mit_inhalt.slug)).json()
    r = client.get(f"/api/lernplaene/{p['id']}")
    assert r.status_code == 200 and r.json() == p
    assert client.get("/api/lernplaene/lp-00000000").status_code == 404


@pytest.mark.parametrize("kennung", ["xyz", "lp-ABCDEF12", "lp-1234567", "..%2Fx", "lp-12345678%2F..%2Fx"])
def test_ungueltige_kennung_404(client, projekte, kennung):
    assert client.get(f"/api/lernplaene/{kennung}").status_code == 404


def test_themen(client, projekt_mit_inhalt):
    r = client.get(f"/api/projekte/{projekt_mit_inhalt.slug}/themen")
    assert r.status_code == 200
    themen = r.json()
    assert themen and all(set(t) >= {"id", "titel", "kurz", "umfang"} for t in themen)
    assert all(t["umfang"] >= 1 for t in themen)


def test_themen_404_und_leer(client, projekte):
    from genut.projekt import Projekt

    assert client.get("/api/projekte/gibt-es-nicht/themen").status_code == 404
    p = Projekt.anlegen("Leer")
    r = client.get(f"/api/projekte/{p.slug}/themen")
    assert r.status_code == 200 and r.json() == []


def test_schalter_aus_404(client, projekt_mit_inhalt, monkeypatch, tmp_path, config_zuruecksetzen):
    s = projekt_mit_inhalt.slug
    p = client.post("/api/lernplaene", json=body(s)).json()
    _config(monkeypatch, tmp_path, "[funktionen]\nlernplan = false\n")
    assert client.get("/api/lernplaene").status_code == 404
    assert client.post("/api/lernplaene", json=body(s)).status_code == 404
    assert client.get(f"/api/lernplaene/{p['id']}").status_code == 404
    assert client.get("/api/lernplaene/lp-00000000").status_code == 404
    assert client.get(f"/api/projekte/{s}/themen").status_code == 200
    ki = client.get("/api/ki").json()
    assert ki["funktionen"]["lernplan"] is False and "lernplan" not in ki["module"]
    _config(monkeypatch, tmp_path, "[funktionen]\nlernplan = true\n")
    assert client.get(f"/api/lernplaene/{p['id']}").status_code == 200


def test_persistenz(projekt_mit_inhalt):
    p = TestClient(app).post("/api/lernplaene", json=body(projekt_mit_inhalt.slug)).json()
    c2 = TestClient(app)
    assert c2.get(f"/api/lernplaene/{p['id']}").json() == p
    assert [x["id"] for x in c2.get("/api/lernplaene").json()["aktuell"]] == [p["id"]]


def test_ki_meldet_funktionen_und_module(client, projekte):
    ki = client.get("/api/ki").json()
    assert "lernplan" in ki["funktionen"] and ki["funktionen"]["lernplan"] is True
    assert "lernplan" in ki["module"]


# ------------------------------------------------------------ Abhaken, Fortschritt, Neu verteilen (US2)

@pytest.fixture
def gross(projekt_mit_inhalt):
    """Projekt, dessen erstes Thema so groß ist, dass es in zwei Teile geteilt wird."""
    d = projekt_mit_inhalt.inhalt()
    d.themen[0].bloecke = d.themen[0].bloecke * 6
    for i, b in enumerate(d.themen[0].bloecke):
        b.id = f"b-{i:08d}"
    projekt_mit_inhalt.inhalt_speichern(d)
    return projekt_mit_inhalt


def stuecke(plan):
    return [t for tag in plan["tage"] for t in tag["themen"]]


def ziel(s, erledigt=True):
    return {k: s[k] for k in ("projekt", "thema_id", "von", "bis")} | {"erledigt": erledigt}


def erledigen(client, pid, **kw):
    return client.put(f"/api/lernplaene/{pid}/erledigt", json=kw)


def neuer_plan(client, slug, **kw):
    r = client.post("/api/lernplaene", json=body(slug, **kw))
    assert r.status_code == 200, r.text
    return r.json()


def test_stueck_abhaken_und_zuruecknehmen(client, projekt_mit_inhalt):
    p = neuer_plan(client, projekt_mit_inhalt.slug)
    s = stuecke(p)[0]
    r = erledigen(client, p["id"], **ziel(s))
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["fortschritt"]["erledigt"] == 1 and a["fortschritt"]["gesamt"] == p["fortschritt"]["gesamt"]
    assert stuecke(a)[0]["status"] == "erledigt" and a["fertig"] is False
    r = erledigen(client, p["id"], **ziel(s, False))
    assert r.status_code == 200
    assert r.json()["fortschritt"]["erledigt"] == 0 and stuecke(r.json())[0]["status"] == "offen"
    assert r.json() == p


def test_abhaken_zweimal_aendert_nichts(client, projekt_mit_inhalt):
    p = neuer_plan(client, projekt_mit_inhalt.slug)
    s = stuecke(p)[0]
    erledigen(client, p["id"], **ziel(s))
    a = erledigen(client, p["id"], **ziel(s)).json()
    assert a["fortschritt"]["erledigt"] == 1


def test_geteiltes_thema_erst_erledigt_wenn_alle_teile(client, gross):
    p = neuer_plan(client, gross.slug)
    teile = [s for s in stuecke(p) if s["teile"] > 1]
    assert len(teile) >= 2 and len({s["thema_id"] for s in teile}) == 1
    gesamt = p["fortschritt"]["gesamt"]
    a = erledigen(client, p["id"], **ziel(teile[0])).json()
    erste = [s for s in stuecke(a) if s["thema_id"] == teile[0]["thema_id"]]
    assert [s["status"] for s in erste].count("erledigt") == 1
    assert a["fortschritt"]["erledigt"] == 1 and a["fortschritt"]["gesamt"] == gesamt
    for t in teile[1:]:
        a = erledigen(client, p["id"], **ziel(t)).json()
    gleiche = [s for s in stuecke(a) if s["thema_id"] == teile[0]["thema_id"]]
    assert all(s["status"] == "erledigt" for s in gleiche)
    assert a["fortschritt"]["erledigt"] == len(teile)
    a = erledigen(client, p["id"], **ziel(teile[0], False)).json()  # ein Teil zurück: Thema nicht mehr erledigt
    gleiche = [s for s in stuecke(a) if s["thema_id"] == teile[0]["thema_id"]]
    assert any(s["status"] != "erledigt" for s in gleiche)
    assert a["fortschritt"]["erledigt"] == len(teile) - 1


def test_wiederholungstag_abhaken_und_zuruecknehmen(client, projekt_mit_inhalt):
    p = neuer_plan(client, projekt_mit_inhalt.slug)
    tag = next(t for t in p["tage"] if t["wiederholung"])
    assert p["fortschritt"]["wiederholung_gesamt"] >= 1 and tag["wiederholung_erledigt"] is False
    a = erledigen(client, p["id"], wiederholung=tag["datum"], erledigt=True).json()
    assert a["fortschritt"]["wiederholung_erledigt"] == 1
    assert next(t for t in a["tage"] if t["datum"] == tag["datum"])["wiederholung_erledigt"] is True
    a = erledigen(client, p["id"], wiederholung=tag["datum"], erledigt=False).json()
    assert a["fortschritt"]["wiederholung_erledigt"] == 0
    assert next(t for t in a["tage"] if t["datum"] == tag["datum"])["wiederholung_erledigt"] is False


def test_erledigt_fehler(client, projekt_mit_inhalt):
    p = neuer_plan(client, projekt_mit_inhalt.slug)
    s = stuecke(p)[0]
    r = erledigen(client, p["id"], **{**ziel(s), "thema_id": "t-gibtsnicht"})
    assert r.status_code == 400 and r.json()["detail"]
    r = erledigen(client, p["id"], **{**ziel(s), "projekt": "gibt-es-nicht"})
    assert r.status_code == 400
    r = erledigen(client, p["id"], **{**ziel(s), "bis": s["bis"] + 99})
    assert r.status_code == 400
    assert erledigen(client, "lp-00000000", **ziel(s)).status_code == 404
    assert client.get(f"/api/lernplaene/{p['id']}").json() == p


def test_fortschritt_in_liste(client, projekt_mit_inhalt):
    p = neuer_plan(client, projekt_mit_inhalt.slug)
    erledigen(client, p["id"], **ziel(stuecke(p)[0]))
    z = client.get("/api/lernplaene").json()["aktuell"][0]
    assert z["fortschritt"]["erledigt"] == 1 and z["fertig"] is False


def test_ueberfaellig_nach_verschiebung_von_heute(client, gross, monkeypatch):
    p = neuer_plan(client, gross.slug)
    erstes = stuecke(p)[0]
    assert p["ueberfaellig"] == 0
    monkeypatch.setattr(logik, "heute", lambda: date.fromisoformat(erstes["datum"]).replace(day=17))
    a = client.get(f"/api/lernplaene/{p['id']}").json()
    assert a["ueberfaellig"] >= 1
    assert stuecke(a)[0]["status"] == "ueberfaellig"
    assert client.get("/api/lernplaene").json()["aktuell"][0]["ueberfaellig"] == a["ueberfaellig"]
    erledigen(client, p["id"], **ziel(stuecke(a)[0]))  # Abhaken hebt die Überfälligkeit auf
    b = client.get(f"/api/lernplaene/{p['id']}").json()
    assert stuecke(b)[0]["status"] == "erledigt" and b["ueberfaellig"] == a["ueberfaellig"] - 1


def test_fertig_wenn_alles_erledigt(client, gross):
    p = neuer_plan(client, gross.slug)
    a = p
    for s in stuecke(p):
        a = erledigen(client, p["id"], **ziel(s)).json()
        assert a["fertig"] is False or s is stuecke(p)[-1]
    assert a["fertig"] is False  # Wiederholungstage fehlen noch
    for tag in p["tage"]:
        if tag["wiederholung"]:
            a = erledigen(client, p["id"], wiederholung=tag["datum"], erledigt=True).json()
    assert a["fertig"] is True
    f = a["fortschritt"]
    assert f["erledigt"] == f["gesamt"] and f["wiederholung_erledigt"] == f["wiederholung_gesamt"]
    assert client.get("/api/lernplaene").json()["aktuell"][0]["fertig"] is True
    a = erledigen(client, p["id"], **ziel(stuecke(p)[0], False)).json()
    assert a["fertig"] is False


def test_erledigt_bleibt_nach_neustart(gross):
    c1 = TestClient(app)
    p = c1.post("/api/lernplaene", json=body(gross.slug)).json()
    s = stuecke(p)[0]
    tag = next(t for t in p["tage"] if t["wiederholung"])
    erledigen(c1, p["id"], **ziel(s))
    a = erledigen(c1, p["id"], wiederholung=tag["datum"], erledigt=True).json()
    c2 = TestClient(app)
    b = c2.get(f"/api/lernplaene/{p['id']}").json()
    assert b == a and b["fortschritt"]["erledigt"] == 1 and b["fortschritt"]["wiederholung_erledigt"] == 1


def test_neu_verteilen_erledigtes_bleibt_und_urspruenglich(client, gross, monkeypatch):
    p = neuer_plan(client, gross.slug)
    erstes = stuecke(p)[0]
    assert all(s["urspruenglich"] is None for s in stuecke(p))
    erledigen(client, p["id"], **ziel(erstes))
    monkeypatch.setattr(logik, "heute", lambda: date(2026, 11, 19))
    vorher = client.get(f"/api/lernplaene/{p['id']}").json()
    assert vorher["ueberfaellig"] >= 1
    r = client.post(f"/api/lernplaene/{p['id']}/neu_verteilen")
    assert r.status_code == 200, r.text
    a = r.json()
    alle = stuecke(a)
    fest = [s for s in alle if s["status"] == "erledigt"]
    assert [(s["thema_id"], s["datum"]) for s in fest] == [(erstes["thema_id"], erstes["datum"])]
    offen = [s for s in alle if s["status"] != "erledigt"]
    assert offen and all(s["datum"] >= "2026-11-19" for s in offen)
    assert a["ueberfaellig"] == 0
    assert any(s["urspruenglich"] == "2026-11-18" for s in offen)
    assert a["fortschritt"]["erledigt"] == 1
    assert client.get(f"/api/lernplaene/{p['id']}").json() == a


def test_neu_verteilen_zu_wenig_tage_gibt_warnung(client, gross, monkeypatch):
    p = neuer_plan(client, gross.slug)
    monkeypatch.setattr(logik, "heute", lambda: date(2026, 12, 7))  # nur noch ein Lerntag vor dem Termin
    r = client.post(f"/api/lernplaene/{p['id']}/neu_verteilen")
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["warnungen"]
    assert {s["datum"] for s in stuecke(a)} == {"2026-12-07"}


def test_neu_verteilen_ohne_lerntag_400_plan_unveraendert(client, gross, monkeypatch):
    p = neuer_plan(client, gross.slug)
    erledigen(client, p["id"], **ziel(stuecke(p)[0]))
    monkeypatch.setattr(logik, "heute", lambda: date(2026, 12, 8))  # kein Lerntag mehr vor dem Termin
    vorher = client.get(f"/api/lernplaene/{p['id']}").json()
    r = client.post(f"/api/lernplaene/{p['id']}/neu_verteilen")
    assert r.status_code == 400 and "Lerntag" in r.json()["detail"]
    assert client.get(f"/api/lernplaene/{p['id']}").json() == vorher
    assert TestClient(app).get(f"/api/lernplaene/{p['id']}").json() == vorher


def test_neu_verteilen_404(client, projekte):
    assert client.post("/api/lernplaene/lp-00000000/neu_verteilen").status_code == 404


def test_schalter_aus_404_auch_fuer_erledigt_und_neu_verteilen(client, projekt_mit_inhalt, monkeypatch, tmp_path,
                                                                config_zuruecksetzen):
    p = neuer_plan(client, projekt_mit_inhalt.slug)
    s = stuecke(p)[0]
    _config(monkeypatch, tmp_path, "[funktionen]\nlernplan = false\n")
    assert erledigen(client, p["id"], **ziel(s)).status_code == 404
    assert erledigen(client, p["id"], wiederholung="2026-12-07", erledigt=True).status_code == 404
    assert client.post(f"/api/lernplaene/{p['id']}/neu_verteilen").status_code == 404
    _config(monkeypatch, tmp_path, "[funktionen]\nlernplan = true\n")
    assert client.get(f"/api/lernplaene/{p['id']}").json()["fortschritt"]["erledigt"] == 0


# ------------------------------------------------------------ Ändern, Löschen, Archiv, Hinweise (US3)

def aendern(client, pid, **kw):
    return client.patch(f"/api/lernplaene/{pid}", json=kw)


def thema_ids(projekt):
    return [t.id for t in projekt.inhalt().themen]


def thema_entfernen(projekt, thema_id):
    d = projekt.inhalt()
    d.themen = [t for t in d.themen if t.id != thema_id]
    projekt.inhalt_speichern(d)


def thema_dazu(projekt, neue_id="t-00000099"):
    d = projekt.inhalt()
    neu = d.themen[0].model_copy(deep=True)
    neu.id, neu.titel = neue_id, "Neues Thema"
    for i, b in enumerate(neu.bloecke):
        b.id = f"b-neu-{i:04d}"
    d.themen.append(neu)
    projekt.inhalt_speichern(d)
    return neue_id


def zweites_projekt():
    from genut.projekt import Projekt
    from tests.conftest import FIX
    from genut.schema import Dokument

    p = Projekt.anlegen("Zweites Projekt")
    p.inhalt_speichern(Dokument.model_validate_json((FIX / "inhalt.json").read_text(encoding="utf-8")))
    return p


def test_patch_wochentage_verteilt_offenen_teil_neu_erledigtes_bleibt(client, projekt_mit_inhalt):
    p = neuer_plan(client, projekt_mit_inhalt.slug)
    erstes = stuecke(p)[0]
    erledigen(client, p["id"], **ziel(erstes))
    r = aendern(client, p["id"], wochentage=[1, 3])
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["id"] == p["id"] and a["wochentage"] == [1, 3] and a["name"] == p["name"]
    alle = stuecke(a)
    fest = [s for s in alle if s["status"] == "erledigt"]
    assert [(s["thema_id"], s["von"], s["bis"], s["datum"]) for s in fest] == \
        [(erstes["thema_id"], erstes["von"], erstes["bis"], erstes["datum"])]
    offen = [s for s in alle if s["status"] != "erledigt"]
    assert offen and all(date.fromisoformat(s["datum"]).weekday() in (1, 3) for s in offen)
    assert all(s["datum"] >= HEUTE.isoformat() for s in offen)
    assert a["fortschritt"]["erledigt"] == 1
    assert client.get(f"/api/lernplaene/{p['id']}").json() == a
    assert TestClient(app).get(f"/api/lernplaene/{p['id']}").json() == a


def test_patch_termin_verschiebt_ende(client, projekt_mit_inhalt):
    p = neuer_plan(client, projekt_mit_inhalt.slug)
    erledigen(client, p["id"], **ziel(stuecke(p)[0]))
    r = aendern(client, p["id"], termin="2026-12-02")
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["termin"] == "2026-12-02"
    assert all(t["datum"] < "2026-12-02" for t in a["tage"])
    offen = [s for s in stuecke(a) if s["status"] != "erledigt"]
    assert offen and all(s["datum"] < "2026-12-02" for s in offen)
    assert a["fortschritt"]["erledigt"] == 1


def test_patch_ausgenommen_laesst_thema_wegfallen(client, projekt_mit_inhalt):
    s = projekt_mit_inhalt.slug
    p = neuer_plan(client, s)
    t1, t2 = thema_ids(projekt_mit_inhalt)[:2]
    assert {x["thema_id"] for x in stuecke(p)} == {t1, t2}
    a = aendern(client, p["id"], ausgenommen=[{"projekt": s, "thema_id": t2}]).json()
    assert {x["thema_id"] for x in stuecke(a)} == {t1}
    assert a["ausgenommen"] == [{"projekt": s, "thema_id": t2}]
    assert a["unverteilt"] == []
    b = aendern(client, p["id"], ausgenommen=[]).json()  # wieder aufnehmen
    assert {x["thema_id"] for x in stuecke(b)} == {t1, t2}


def test_patch_projekt_entfernen_und_hinzufuegen(client, projekt_mit_inhalt):
    s1 = projekt_mit_inhalt.slug
    z = zweites_projekt()
    p = neuer_plan(client, s1, projekte=[s1, z.slug])
    assert {x["projekt"] for x in stuecke(p)} == {s1, z.slug}
    a = aendern(client, p["id"], projekte=[s1]).json()
    assert a["projekte"] == [s1] and {x["projekt"] for x in stuecke(a)} == {s1}
    b = aendern(client, p["id"], projekte=[s1, z.slug]).json()
    assert {x["projekt"] for x in stuecke(b)} == {s1, z.slug}


def test_patch_nur_name(client, projekt_mit_inhalt):
    p = neuer_plan(client, projekt_mit_inhalt.slug)
    a = aendern(client, p["id"], name="Neuer Name").json()
    assert a["name"] == "Neuer Name"
    assert a["termin"] == p["termin"] and a["wochentage"] == p["wochentage"]
    assert client.get("/api/lernplaene").json()["aktuell"][0]["name"] == "Neuer Name"


@pytest.mark.parametrize("aender, meldung", [
    ({"name": "  "}, "Name"),
    ({"termin": "2026-11-16"}, "Zukunft"),
    ({"termin": "2026-11-01"}, "Zukunft"),
    ({"wochentage": []}, "Wochentag"),
    ({"projekte": ["gibt-es-nicht"]}, "Inhalt"),
    ({"termin": "2026-11-20", "wochentage": [5]}, "Lerntag"),
])
def test_patch_fehler_400_plan_unveraendert(client, projekt_mit_inhalt, aender, meldung):
    p = neuer_plan(client, projekt_mit_inhalt.slug)
    r = aendern(client, p["id"], **aender)
    assert r.status_code == 400 and meldung in r.json()["detail"]
    assert client.get(f"/api/lernplaene/{p['id']}").json() == p
    assert TestClient(app).get(f"/api/lernplaene/{p['id']}").json() == p


def test_patch_alle_themen_ausgenommen_400(client, projekt_mit_inhalt):
    s = projekt_mit_inhalt.slug
    p = neuer_plan(client, s)
    aus = [{"projekt": s, "thema_id": t} for t in thema_ids(projekt_mit_inhalt)]
    r = aendern(client, p["id"], ausgenommen=aus)
    assert r.status_code == 400 and "ausgenommen" in r.json()["detail"]
    assert client.get(f"/api/lernplaene/{p['id']}").json() == p


def test_patch_404(client, projekte):
    assert aendern(client, "lp-00000000", name="x").status_code == 404


def test_delete_entfernt_plan_projekte_bleiben(client, projekt_mit_inhalt):
    s = projekt_mit_inhalt.slug
    p = neuer_plan(client, s)
    r = client.delete(f"/api/lernplaene/{p['id']}")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert client.get(f"/api/lernplaene/{p['id']}").status_code == 404
    assert client.get("/api/lernplaene").json() == {"aktuell": [], "archiv": []}
    assert client.delete(f"/api/lernplaene/{p['id']}").status_code == 404
    assert client.get(f"/api/projekte/{s}/themen").status_code == 200
    assert len(client.get(f"/api/projekte/{s}/themen").json()) == len(thema_ids(projekt_mit_inhalt))
    assert TestClient(app).get(f"/api/lernplaene/{p['id']}").status_code == 404


def test_delete_404(client, projekte):
    assert client.delete("/api/lernplaene/lp-00000000").status_code == 404


def test_archiv_wenn_termin_vor_heute(client, projekt_mit_inhalt, monkeypatch):
    p = neuer_plan(client, projekt_mit_inhalt.slug)
    assert p["archiv"] is False
    monkeypatch.setattr(logik, "heute", lambda: date(2026, 12, 9))  # Termin selbst: noch nicht Archiv
    assert client.get(f"/api/lernplaene/{p['id']}").json()["archiv"] is False
    assert [x["id"] for x in client.get("/api/lernplaene").json()["aktuell"]] == [p["id"]]
    monkeypatch.setattr(logik, "heute", lambda: date(2026, 12, 10))
    assert client.get(f"/api/lernplaene/{p['id']}").json()["archiv"] is True
    liste = client.get("/api/lernplaene").json()
    assert liste["aktuell"] == [] and [x["id"] for x in liste["archiv"]] == [p["id"]]
    assert client.delete(f"/api/lernplaene/{p['id']}").status_code == 200  # Archiv lässt sich löschen


def test_geloeschtes_thema_gibt_hinweis_statt_fehler(client, projekt_mit_inhalt):
    p = neuer_plan(client, projekt_mit_inhalt.slug)
    t1, t2 = thema_ids(projekt_mit_inhalt)[:2]
    thema_entfernen(projekt_mit_inhalt, t2)
    r = client.get(f"/api/lernplaene/{p['id']}")
    assert r.status_code == 200, r.text
    a = r.json()
    assert {x["thema_id"] for x in stuecke(a)} == {t1}
    assert any("Thema" in h and "nicht mehr" in h for h in a["hinweise"])
    assert client.get("/api/lernplaene").status_code == 200
    n = client.post(f"/api/lernplaene/{p['id']}/neu_verteilen")
    assert n.status_code == 200 and {x["thema_id"] for x in stuecke(n.json())} == {t1}


def test_geloeschtes_projekt_gibt_hinweis_statt_fehler(client, projekt_mit_inhalt):
    s1 = projekt_mit_inhalt.slug
    z = zweites_projekt()
    p = neuer_plan(client, s1, projekte=[s1, z.slug])
    z.loeschen()
    r = client.get(f"/api/lernplaene/{p['id']}")
    assert r.status_code == 200, r.text
    a = r.json()
    assert {x["projekt"] for x in stuecke(a)} == {s1}
    assert any(z.slug in h and "nicht mehr" in h for h in a["hinweise"])
    liste = client.get("/api/lernplaene")
    assert liste.status_code == 200 and len(liste.json()["aktuell"]) == 1
    # Abhaken des verbliebenen Projekts funktioniert weiter
    assert erledigen(client, p["id"], **ziel(stuecke(a)[0])).status_code == 200


def test_neues_thema_erscheint_unter_unverteilt(client, projekt_mit_inhalt):
    p = neuer_plan(client, projekt_mit_inhalt.slug)
    assert p["unverteilt"] == []
    neu = thema_dazu(projekt_mit_inhalt)
    a = client.get(f"/api/lernplaene/{p['id']}").json()
    assert [u["thema_id"] for u in a["unverteilt"]] == [neu]
    assert a["unverteilt"][0]["datum"] is None and a["unverteilt"][0]["titel"] == "Neues Thema"
    assert neu not in {x["thema_id"] for x in stuecke(a)}
    assert a["hinweise"]
    b = client.post(f"/api/lernplaene/{p['id']}/neu_verteilen").json()
    assert b["unverteilt"] == [] and neu in {x["thema_id"] for x in stuecke(b)}


def test_ausgenommenes_neues_thema_ist_nicht_unverteilt(client, projekt_mit_inhalt):
    s = projekt_mit_inhalt.slug
    p = neuer_plan(client, s)
    neu = thema_dazu(projekt_mit_inhalt)
    a = aendern(client, p["id"], ausgenommen=[{"projekt": s, "thema_id": neu}]).json()
    assert a["unverteilt"] == [] and neu not in {x["thema_id"] for x in stuecke(a)}


def test_zwei_plaene_unabhaengig(client, projekt_mit_inhalt):
    s = projekt_mit_inhalt.slug
    a = neuer_plan(client, s, name="A")
    b = neuer_plan(client, s, name="B", termin="2026-12-02", wochentage=[1, 3])
    assert a["id"] != b["id"]
    erledigen(client, a["id"], **ziel(stuecke(a)[0]))
    assert client.get(f"/api/lernplaene/{b['id']}").json() == b
    aendern(client, b["id"], name="B2", wochentage=[4])
    ga = client.get(f"/api/lernplaene/{a['id']}").json()
    assert ga["name"] == "A" and ga["wochentage"] == [0, 2, 5] and ga["fortschritt"]["erledigt"] == 1
    assert client.delete(f"/api/lernplaene/{b['id']}").status_code == 200
    assert client.get(f"/api/lernplaene/{a['id']}").status_code == 200
    assert [x["id"] for x in client.get("/api/lernplaene").json()["aktuell"]] == [a["id"]]


@pytest.mark.parametrize("kennung", ["xyz", "lp-ABCDEF12", "lp-1234567", "lp-12345678%2F..%2Fx"])
def test_ungueltige_kennung_404_auch_patch_delete(client, projekte, kennung):
    assert client.patch(f"/api/lernplaene/{kennung}", json={"name": "x"}).status_code == 404
    assert client.delete(f"/api/lernplaene/{kennung}").status_code == 404
    assert client.post(f"/api/lernplaene/{kennung}/neu_verteilen").status_code == 404


def test_schalter_aus_404_auch_fuer_patch_und_delete(client, projekt_mit_inhalt, monkeypatch, tmp_path,
                                                      config_zuruecksetzen):
    p = neuer_plan(client, projekt_mit_inhalt.slug)
    _config(monkeypatch, tmp_path, "[funktionen]\nlernplan = false\n")
    assert aendern(client, p["id"], name="x").status_code == 404
    assert client.delete(f"/api/lernplaene/{p['id']}").status_code == 404
    _config(monkeypatch, tmp_path, "[funktionen]\nlernplan = true\n")
    a = client.get(f"/api/lernplaene/{p['id']}")
    assert a.status_code == 200 and a.json()["name"] == "Plan"
