"""HTTP-Schnittstelle der mündlichen Prüfung (specs/005-muendliche-pruefung/contracts/api.md), Fake-Prüfer."""
import threading

import pytest
from fastapi.testclient import TestClient

from genut.config import laden
from genut.modelle.base import ModellFehler
from genut.server import app

from .fake import FakeModell, einsetzen

T1, T2 = "t-00000001", "t-00000002"
LANG = "Das bestimmte Integral ist der Grenzwert der Riemann-Summen und entspricht der orientierten Fläche."


@pytest.fixture(autouse=True)
def _schalter_an(monkeypatch, tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[funktionen]\npruefung = true\n", encoding="utf-8")
    monkeypatch.setenv("GENUT_CONFIG", str(cfg))
    laden.cache_clear()
    yield
    laden.cache_clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def s(projekt_mit_inhalt):
    return projekt_mit_inhalt.slug


def basis(s):
    return f"/api/projekte/{s}/pruefungen"


def start(client, s, fragen=3, themen=(T1, T2)):
    r = client.post(basis(s), json={"themen": list(themen), "fragen": fragen})
    assert r.status_code == 200, r.text
    return r.json()


def weiter_(punkte):
    return {"aktion": "weiter", "text": None, "punkte": punkte, "anmerkung": "ok"}


def test_ganzer_lauf(client, s, monkeypatch):
    fake = einsetzen(monkeypatch, FakeModell(zug=[weiter_(2), weiter_(2), weiter_(2)]))
    z = start(client, s)
    assert z["status"] == "laeuft" and z["aktuelle_frage"] == 1 and z["fragen_anzahl"] == 3
    assert z["wartet"] is False and z["ergebnis"] is None and [n["typ"] for n in z["verlauf"]] == ["frage"]
    pid = z["id"]
    assert pid.startswith("pr-")
    assert client.get(basis(s)).json()["laufend"] == pid
    for k in (2, 3):
        z = client.post(f"{basis(s)}/{pid}/antwort", json={"text": LANG}).json()
        assert z["status"] == "laeuft" and z["aktuelle_frage"] == k
    z = client.post(f"{basis(s)}/{pid}/antwort", json={"text": LANG}).json()
    assert z["status"] == "abgeschlossen" and z["aktuelle_frage"] is None
    e = z["ergebnis"]
    assert e["note"] == 1 and e["punkte"] == 6 and e["maximal"] == 6 and e["verkuerzt"] is False
    assert all(lu["link"] for lu in e["luecken"])
    assert client.get(f"{basis(s)}/{pid}").json() == z
    liste = client.get(basis(s)).json()
    assert liste["laufend"] is None and liste["liste"][0]["id"] == pid and liste["liste"][0]["note"] == 1
    assert set(liste["liste"][0]) == {"id", "erstellt", "status", "themen", "fragen", "note", "note_name"}
    assert fake.anzahl("plan") == 1 and fake.anzahl("bewertung") == 1


def test_plan_nie_in_antworten(client, s, monkeypatch):
    einsetzen(monkeypatch, FakeModell())
    antworten = [start(client, s)]
    pid = antworten[0]["id"]
    antworten.append(client.get(f"{basis(s)}/{pid}").json())
    antworten.append(client.get(basis(s)).json())
    antworten.append(client.post(f"{basis(s)}/{pid}/antwort", json={"text": LANG}).json())
    antworten.append(client.post(f"{basis(s)}/{pid}/beenden").json())
    for a in antworten:
        text = str(a)
        assert "Kernbegriff zu" not in text and "Ein Beispiel zu" not in text
        assert "plan" not in a and "erwartung" not in text
    assert client.get(f"{basis(s)}/{pid}").json()["status"] == "verkuerzt"


def test_nachfrage_bei_kurzer_antwort(client, s, monkeypatch):
    einsetzen(monkeypatch, FakeModell())
    pid = start(client, s)["id"]
    z = client.post(f"{basis(s)}/{pid}/antwort", json={"text": "Fläche"}).json()
    assert z["aktuelle_frage"] == 1 and z["verlauf"][-1]["typ"] == "nachfrage"
    assert z["wartet"] is False


def test_leere_antwort_ist_kein_fehler(client, s, monkeypatch):
    fake = einsetzen(monkeypatch, FakeModell())
    pid = start(client, s)["id"]
    r = client.post(f"{basis(s)}/{pid}/antwort", json={"text": ""})
    assert r.status_code == 200 and r.json()["aktuelle_frage"] == 2
    assert fake.anzahl("zug") == 0


def test_beenden_verkuerzt(client, s, monkeypatch):
    einsetzen(monkeypatch, FakeModell(zug=[weiter_(2)]))
    pid = start(client, s)["id"]
    client.post(f"{basis(s)}/{pid}/antwort", json={"text": LANG})
    z = client.post(f"{basis(s)}/{pid}/beenden").json()
    assert z["status"] == "verkuerzt" and z["ergebnis"]["verkuerzt"] is True
    assert client.post(f"{basis(s)}/{pid}/beenden").status_code == 409
    assert client.post(f"{basis(s)}/{pid}/antwort", json={"text": LANG}).status_code == 409


def test_loeschen(client, s, monkeypatch):
    einsetzen(monkeypatch, FakeModell())
    pid = start(client, s)["id"]
    assert client.delete(f"{basis(s)}/{pid}").json() == {"ok": True}
    assert client.get(f"{basis(s)}/{pid}").status_code == 404
    assert client.delete(f"{basis(s)}/{pid}").status_code == 404
    assert client.get(basis(s)).json() == {"liste": [], "laufend": None}


# ---------------------------------------------------------------- 404

def test_404_projekt_und_kennung(client, s, monkeypatch):
    einsetzen(monkeypatch, FakeModell())
    assert client.get("/api/projekte/gibt-es-nicht/pruefungen").status_code == 404
    assert client.post("/api/projekte/gibt-es-nicht/pruefungen", json={"themen": [T1]}).status_code == 404
    assert client.get(f"{basis(s)}/pr-00000000").status_code == 404
    assert client.get(f"{basis(s)}/unsinn").status_code == 404
    assert client.post(f"{basis(s)}/pr-00000000/antwort", json={"text": "x"}).status_code == 404
    assert client.post(f"{basis(s)}/pr-00000000/weiter").status_code == 404
    assert client.post(f"{basis(s)}/pr-00000000/beenden").status_code == 404
    assert client.delete(f"{basis(s)}/pr-00000000").status_code == 404


# ---------------------------------------------------------------- 400

@pytest.mark.parametrize("body", [
    {"themen": [], "fragen": 3},
    {"fragen": 3},
    {"themen": "t-00000001", "fragen": 3},
    {"themen": [T1], "fragen": 2},
    {"themen": [T1], "fragen": 13},
    {"themen": [T1], "fragen": "6"},
    {"themen": [T1], "fragen": True},
    {"themen": ["t-unbekannt"], "fragen": 3},
])
def test_start_ungueltig_400(client, s, monkeypatch, body):
    fake = einsetzen(monkeypatch, FakeModell())
    r = client.post(basis(s), json=body)
    assert r.status_code == 400 and r.json()["detail"]
    assert fake.anzahl() == 0 and client.get(basis(s)).json() == {"liste": [], "laufend": None}


def test_projekt_ohne_inhalt_400(client, projekte, monkeypatch):
    from genut.projekt import Projekt

    einsetzen(monkeypatch, FakeModell())
    p = Projekt.anlegen("Leer")
    r = client.post(basis(p.slug), json={"themen": [T1], "fragen": 3})
    assert r.status_code == 400 and "Inhalt" in r.json()["detail"]


def test_antwort_zu_lang_400(client, s, monkeypatch):
    fake = einsetzen(monkeypatch, FakeModell())
    pid = start(client, s)["id"]
    assert client.post(f"{basis(s)}/{pid}/antwort", json={"text": "x" * 4001}).status_code == 400
    assert client.post(f"{basis(s)}/{pid}/antwort", json={"text": 5}).status_code == 400
    assert fake.anzahl("zug") == 0
    assert client.get(f"{basis(s)}/{pid}").json()["aktuelle_frage"] == 1


# ---------------------------------------------------------------- 409

def test_laufende_blockiert_zweite(client, s, monkeypatch):
    fake = einsetzen(monkeypatch, FakeModell())
    pid = start(client, s)["id"]
    r = client.post(basis(s), json={"themen": [T1], "fragen": 3})
    assert r.status_code == 409 and "läuft" in r.json()["detail"]
    assert fake.anzahl("plan") == 1
    client.post(f"{basis(s)}/{pid}/beenden")
    assert client.post(basis(s), json={"themen": [T1], "fragen": 3}).status_code == 200


def test_weiter_ohne_wartendes_409(client, s, monkeypatch):
    einsetzen(monkeypatch, FakeModell())
    pid = start(client, s)["id"]
    assert client.post(f"{basis(s)}/{pid}/weiter").status_code == 409


def test_gleichzeitige_antwort_409(client, s, monkeypatch):
    innen, frei = threading.Event(), threading.Event()

    def haengt(prompt):
        innen.set()
        assert frei.wait(10)
        return weiter_(2)

    einsetzen(monkeypatch, FakeModell(zug=[haengt]))
    pid = start(client, s)["id"]
    erste = {}
    t = threading.Thread(target=lambda: erste.setdefault("r", client.post(f"{basis(s)}/{pid}/antwort", json={"text": LANG})))
    t.start()
    try:
        assert innen.wait(10)
        r = client.post(f"{basis(s)}/{pid}/antwort", json={"text": LANG})
        assert r.status_code == 409
    finally:
        frei.set()
        t.join(10)
    assert erste["r"].status_code == 200


# ---------------------------------------------------------------- 502

def test_start_502_legt_nichts_an(client, s, monkeypatch):
    einsetzen(monkeypatch, FakeModell(plan=[ModellFehler("kaputt")]))
    r = client.post(basis(s), json={"themen": [T1], "fragen": 3})
    assert r.status_code == 502 and "Prüfer" in r.json()["detail"]
    assert client.get(basis(s)).json() == {"liste": [], "laufend": None}


def test_zug_502_dann_weiter_versuchen(client, s, monkeypatch):
    einsetzen(monkeypatch, FakeModell(zug=[ModellFehler("kaputt"), weiter_(2)]))
    pid = start(client, s)["id"]
    r = client.post(f"{basis(s)}/{pid}/antwort", json={"text": LANG})
    assert r.status_code == 502
    z = client.get(f"{basis(s)}/{pid}").json()
    assert z["wartet"] is True and z["aktuelle_frage"] == 1
    assert client.post(f"{basis(s)}/{pid}/antwort", json={"text": LANG}).status_code == 409
    z = client.post(f"{basis(s)}/{pid}/weiter").json()
    assert z["wartet"] is False and z["aktuelle_frage"] == 2


def test_bewertung_502_dann_weiter_versuchen(client, s, monkeypatch):
    einsetzen(monkeypatch, FakeModell(bewertung=[ModellFehler("kaputt")]))
    pid = start(client, s, fragen=3)["id"]
    for _ in range(2):
        assert client.post(f"{basis(s)}/{pid}/antwort", json={"text": LANG}).status_code == 200
    assert client.post(f"{basis(s)}/{pid}/antwort", json={"text": LANG}).status_code == 502
    z = client.get(f"{basis(s)}/{pid}").json()
    assert z["status"] == "laeuft" and z["wartet"] is True and z["ergebnis"] is None
    z = client.post(f"{basis(s)}/{pid}/weiter").json()
    assert z["status"] == "abgeschlossen" and z["ergebnis"]["verkuerzt"] is False


# ---------------------------------------------------------------- Schalter

def test_schalter_aus_404_ueberall(client, s, monkeypatch, tmp_path):
    einsetzen(monkeypatch, FakeModell())
    pid = start(client, s)["id"]
    cfg = tmp_path / "aus.toml"
    cfg.write_text("[funktionen]\npruefung = false\n", encoding="utf-8")
    monkeypatch.setenv("GENUT_CONFIG", str(cfg))
    laden.cache_clear()
    b = basis(s)
    for methode, pfad, kw in [("get", b, {}), ("post", b, {"json": {"themen": [T1], "fragen": 3}}),
                              ("get", f"{b}/{pid}", {}), ("post", f"{b}/{pid}/antwort", {"json": {"text": "x"}}),
                              ("post", f"{b}/{pid}/weiter", {}), ("post", f"{b}/{pid}/beenden", {}),
                              ("delete", f"{b}/{pid}", {}), ("get", f"{b}/pr-00000000", {})]:
        assert getattr(client, methode)(pfad, **kw).status_code == 404, (methode, pfad)
    assert client.get(f"/api/projekte/{s}/themen").status_code == 200
    ki = client.get("/api/ki").json()
    assert ki["funktionen"]["pruefung"] is False and "pruefung" not in ki["module"]
    cfg.write_text("[funktionen]\npruefung = true\n", encoding="utf-8")
    laden.cache_clear()
    assert client.get(f"{b}/{pid}").status_code == 200  # nichts ging verloren


def test_ki_enthaelt_funktion(client):
    ki = client.get("/api/ki").json()
    assert ki["funktionen"]["pruefung"] is True and "pruefung" in ki["module"]


# ---------------------------------------------------------------- US3 (T014): Liste, Fortsetzen, Wiederholen

def _abschliessen(client, s, pid, n=3):
    for _ in range(n):
        z = client.post(f"{basis(s)}/{pid}/antwort", json={"text": LANG}).json()
    return z


def test_liste_mit_noten_neueste_zuerst(client, s, monkeypatch):
    einsetzen(monkeypatch, FakeModell(zug=[weiter_(2)] * 3 + [weiter_(1)] * 3))
    a = start(client, s)["id"]
    _abschliessen(client, s, a)
    from datetime import timedelta
    from genut.funktionen.pruefung import logik

    alt = logik.laden(s, a)  # erstellt hat Sekundenauflösung: die ältere ausdrücklich früher datieren
    alt.erstellt -= timedelta(hours=1)
    logik.speichern(s, alt)
    b = start(client, s, fragen=4, themen=(T1,))["id"]
    _abschliessen(client, s, b, 4)
    liste = client.get(basis(s)).json()
    assert liste["laufend"] is None
    assert [e["id"] for e in liste["liste"]] == [b, a]
    assert liste["liste"][1]["note"] == 1 and liste["liste"][1]["note_name"]
    assert liste["liste"][0]["note"] is not None and liste["liste"][0]["fragen"] == 4
    assert all(e["status"] == "abgeschlossen" and e["erstellt"] and len(e["themen"]) for e in liste["liste"])
    assert len(liste["liste"][1]["themen"]) == 2 and len(liste["liste"][0]["themen"]) == 1


def test_fortsetzen_nach_neustart(client, s, monkeypatch):
    fake = einsetzen(monkeypatch, FakeModell())
    pid = start(client, s)["id"]
    vor = client.post(f"{basis(s)}/{pid}/antwort", json={"text": LANG}).json()
    assert vor["aktuelle_frage"] == 2
    neu = TestClient(app)  # "Neustart": neuer Client, dieselben Dateien
    assert neu.get(basis(s)).json()["laufend"] == pid
    nach = neu.get(f"{basis(s)}/{pid}").json()
    assert nach == vor and nach["verlauf"] == vor["verlauf"]
    z = _abschliessen(neu, s, pid, 2)
    assert z["status"] == "abgeschlossen" and z["ergebnis"] is not None
    assert fake.anzahl("plan") == 1


def test_fortsetzen_wartende_nach_neustart(client, s, monkeypatch):
    einsetzen(monkeypatch, FakeModell(zug=[ModellFehler("kaputt"), weiter_(2)]))
    pid = start(client, s)["id"]
    assert client.post(f"{basis(s)}/{pid}/antwort", json={"text": LANG}).status_code == 502
    neu = TestClient(app)
    assert neu.get(f"{basis(s)}/{pid}").json()["wartet"] is True
    z = neu.post(f"{basis(s)}/{pid}/weiter").json()
    assert z["wartet"] is False and z["aktuelle_frage"] == 2


def test_nochmal_mit_denselben_themen(client, s, monkeypatch):
    fake = einsetzen(monkeypatch, FakeModell())
    a = start(client, s, fragen=4, themen=(T2,))
    client.post(f"{basis(s)}/{a['id']}/beenden")
    # die Oberfläche startet mit themen und fragen_gewuenscht aus dem gespeicherten Zustand neu
    alt = client.get(f"{basis(s)}/{a['id']}").json()
    b = start(client, s, fragen=alt["fragen_gewuenscht"], themen=alt["themen"])
    assert b["id"] != a["id"] and b["themen"] == [T2] and b["fragen_gewuenscht"] == 4 and b["fragen_anzahl"] == 4
    assert b["status"] == "laeuft" and fake.anzahl("plan") == 2
    assert len(client.get(basis(s)).json()["liste"]) == 2


def test_loeschen_aus_liste_laesst_andere_und_lernseite(client, s, monkeypatch, projekt_mit_inhalt):
    einsetzen(monkeypatch, FakeModell())
    a = start(client, s)["id"]
    client.post(f"{basis(s)}/{a}/beenden")
    b = start(client, s)["id"]
    inhalt_vorher = projekt_mit_inhalt.inhalt_pfad.read_bytes()
    assert client.delete(f"{basis(s)}/{a}").json() == {"ok": True}
    liste = client.get(basis(s)).json()
    assert [e["id"] for e in liste["liste"]] == [b] and liste["laufend"] == b
    assert projekt_mit_inhalt.inhalt_pfad.read_bytes() == inhalt_vorher
    assert client.get(f"/api/projekte/{s}/themen").status_code == 200


def test_geloeschtes_thema_link_entfaellt_mit_hinweis(client, s, monkeypatch, projekt_mit_inhalt):
    bew = {"begruendung": "x", "luecken": [{"thema_id": T1, "hinweis": "h1"}, {"thema_id": T2, "hinweis": "h2"}],
           "rueckmeldungen": [{"nr": k, "fehlte": "f", "stoff_hinweis": "s"} for k in (1, 2, 3)]}
    einsetzen(monkeypatch, FakeModell(zug=[weiter_(1)] * 3, bewertung=[bew]))
    pid = start(client, s)["id"]
    z = _abschliessen(client, s, pid)
    assert [lu["link"] for lu in z["ergebnis"]["luecken"]] == [f"#/p/{s}/vorschau/{T1}", f"#/p/{s}/vorschau/{T2}"]
    assert z["hinweis"] is None
    doc = projekt_mit_inhalt.inhalt()
    doc.themen = [t for t in doc.themen if t.id != T1]
    projekt_mit_inhalt.inhalt_speichern(doc)
    z = TestClient(app).get(f"{basis(s)}/{pid}").json()
    links = {lu["thema_id"]: lu["link"] for lu in z["ergebnis"]["luecken"]}
    assert links[T1] is None and links[T2] == f"#/p/{s}/vorschau/{T2}"
    assert "nicht mehr" in z["hinweis"]
    e = client.get(basis(s)).json()["liste"][0]  # Liste bleibt lesbar, Themenname fällt auf die Kennung zurück
    assert T1 in e["themen"] and e["note"] == z["ergebnis"]["note"]


def test_projekt_loeschen_nimmt_pruefungen_mit(client, s, monkeypatch, projekt_mit_inhalt):
    einsetzen(monkeypatch, FakeModell())
    pid = start(client, s)["id"]
    ordner = projekt_mit_inhalt.ordner / "pruefungen"
    assert any(ordner.glob("pr-*.json"))
    assert client.delete(f"/api/projekte/{s}").json() == {"ok": True}
    assert not ordner.exists()
    assert client.get(basis(s)).status_code == 404
    assert client.get(f"{basis(s)}/{pid}").status_code == 404
