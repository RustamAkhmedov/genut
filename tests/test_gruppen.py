from genut.schema import ProjektMeta


def test_projekt_meta_ohne_gruppe_laedt_mit_none():
    meta = ProjektMeta(name="Test", slug="test")
    assert meta.gruppe is None


import pytest

from genut import gruppen
from genut.projekt import Projekt


def test_register_leer_und_kaputt(projekte):
    assert gruppen.laden() == []
    projekte.mkdir(parents=True)
    (projekte / "gruppen.json").write_text("{kaputt", encoding="utf-8")
    assert gruppen.laden() == []


def test_anlegen_und_existiert(projekte):
    g = gruppen.anlegen("  Schularbeit  ")
    assert g["name"] == "Schularbeit"
    assert len(g["id"]) == 10 and g["id"].startswith("g-")
    assert gruppen.existiert(g["id"])
    assert not gruppen.existiert("g-../../x")
    assert gruppen.laden() == [g]


def test_namensregeln(projekte):
    gruppen.anlegen("Mathe")
    for schlecht in ("", "   ", "x" * 61):
        with pytest.raises(gruppen.NameFehler):
            gruppen.anlegen(schlecht)
    with pytest.raises(gruppen.NameVergeben):
        gruppen.anlegen("MATHE")


def test_umbenennen(projekte):
    a = gruppen.anlegen("Mathe")
    gruppen.anlegen("Physik")
    assert gruppen.umbenennen(a["id"], "MATHE")["name"] == "MATHE"
    with pytest.raises(gruppen.NameVergeben):
        gruppen.umbenennen(a["id"], "physik")
    with pytest.raises(gruppen.GruppeUnbekannt):
        gruppen.umbenennen("g-00000000", "Neu")
    with pytest.raises(gruppen.GruppeUnbekannt):
        gruppen.umbenennen("../x", "Neu")


def test_loeschen_verschiebt_projekte(projekte):
    g = gruppen.anlegen("Mathe")
    p = Projekt.anlegen("Eins")
    m = p.meta()
    m.gruppe = g["id"]
    p.meta_speichern(m)
    Projekt.anlegen("Zwei")
    assert gruppen.loeschen(g["id"]) == 1
    assert Projekt.laden("eins").meta().gruppe is None
    assert gruppen.laden() == []
    with pytest.raises(gruppen.GruppeUnbekannt):
        gruppen.loeschen(g["id"])


# ---------------------------------------------------------------- Register (Ergänzungen)

def test_loeschen_laesst_andere_projekte_und_felder_unveraendert(projekte):
    g = gruppen.anlegen("Mathe")
    h = gruppen.anlegen("Physik")
    p = Projekt.anlegen("Eins")
    q = Projekt.anlegen("Zwei")
    for proj, gr in ((p, g), (q, h)):
        m = proj.meta()
        m.gruppe = gr["id"]
        proj.meta_speichern(m)
    vorher = Projekt.laden("zwei").meta()
    assert gruppen.loeschen(g["id"]) == 1
    assert Projekt.laden("zwei").meta() == vorher
    nachher = Projekt.laden("eins").meta()
    assert nachher.gruppe is None and nachher.name == "Eins"
    assert gruppen.laden() == [h]


def test_loeschen_unbekannte_kennung(projekte):
    for schlecht in ("g-00000000", "../x", ""):
        with pytest.raises(gruppen.GruppeUnbekannt):
            gruppen.loeschen(schlecht)


def test_name_genau_60_zeichen_ok(projekte):
    assert gruppen.anlegen("x" * 60)["name"] == "x" * 60


# ---------------------------------------------------------------- API

@pytest.fixture
def client(projekte):
    from fastapi.testclient import TestClient

    from genut.server import app

    return TestClient(app)


def test_api_gruppen_anlegen_und_lesen(client):
    r = client.post("/api/gruppen", json={"name": "Mathe"})
    assert r.status_code == 200
    g = r.json()
    assert g["name"] == "Mathe" and g["anzahl"] == 0 and g["id"].startswith("g-")
    assert client.get("/api/gruppen").json() == [g]


def test_api_gruppen_fehler(client):
    client.post("/api/gruppen", json={"name": "Mathe"})
    assert client.post("/api/gruppen", json={"name": "MATHE"}).status_code == 409
    assert client.post("/api/gruppen", json={"name": ""}).status_code == 400
    assert client.post("/api/gruppen", json={"name": "x" * 61}).status_code == 400
    assert client.patch("/api/gruppen/g-00000000", json={"name": "Neu"}).status_code == 404
    assert client.delete("/api/gruppen/g-00000000").status_code == 404
    assert client.delete("/api/gruppen/unsinn").status_code == 404


def test_api_gruppen_sortiert_und_umbenennen(client):
    b = client.post("/api/gruppen", json={"name": "bio"}).json()
    client.post("/api/gruppen", json={"name": "Anna"})
    client.post("/api/gruppen", json={"name": "Chemie"})
    assert [g["name"] for g in client.get("/api/gruppen").json()] == ["Anna", "bio", "Chemie"]
    r = client.patch(f"/api/gruppen/{b['id']}", json={"name": "Zoo"})
    assert r.status_code == 200 and r.json()["name"] == "Zoo"
    assert client.patch(f"/api/gruppen/{b['id']}", json={"name": "anna"}).status_code == 409
    assert client.patch(f"/api/gruppen/{b['id']}", json={"name": " "}).status_code == 400


def test_api_projekt_gruppe_setzen_loesen_unbekannt(client):
    g = client.post("/api/gruppen", json={"name": "Mathe"}).json()
    client.post("/api/projekte", json={"name": "Eins"})
    r = client.patch("/api/projekte/eins", json={"gruppe": g["id"]})
    assert r.status_code == 200 and r.json()["gruppe"] == g["id"]
    assert client.get("/api/gruppen").json()[0]["anzahl"] == 1
    assert client.patch("/api/projekte/eins", json={"gruppe": "g-00000000"}).status_code == 400
    assert client.get("/api/projekte/eins").json()["gruppe"] == g["id"]
    # anderes Feld ändern lässt die Gruppe unberührt
    assert client.patch("/api/projekte/eins", json={"name": "Eins neu"}).json()["gruppe"] == g["id"]
    r = client.patch("/api/projekte/eins", json={"gruppe": ""})
    assert r.status_code == 200 and r.json()["gruppe"] is None
    assert client.get("/api/gruppen").json()[0]["anzahl"] == 0


def test_api_gruppe_loeschen_verschiebt(client):
    g = client.post("/api/gruppen", json={"name": "Mathe"}).json()
    client.post("/api/projekte", json={"name": "Eins"})
    client.patch("/api/projekte/eins", json={"gruppe": g["id"]})
    assert client.delete(f"/api/gruppen/{g['id']}").json() == {"ok": True, "verschoben": 1}
    assert client.get("/api/projekte/eins").json()["gruppe"] is None
    assert client.get("/api/gruppen").json() == []


def test_persistenz_nach_neustart(projekte):
    from fastapi.testclient import TestClient

    from genut.server import app

    c1 = TestClient(app)
    g = c1.post("/api/gruppen", json={"name": "Mathe"}).json()
    c1.post("/api/projekte", json={"name": "Eins"})
    c1.patch("/api/projekte/eins", json={"gruppe": g["id"]})
    c2 = TestClient(app)
    assert c2.get("/api/gruppen").json() == [{**g, "anzahl": 1}]
    assert c2.get("/api/projekte/eins").json()["gruppe"] == g["id"]


# ---------------------------------------------------------------- Projektliste (FR-011, FR-012)

def test_projektliste_altbestand_und_unbekannte_gruppe(client):
    import json

    g = client.post("/api/gruppen", json={"name": "Mathe"}).json()
    leer = client.post("/api/gruppen", json={"name": "Leer"}).json()
    for n in ("Alt", "Waise", "Drin"):
        client.post("/api/projekte", json={"name": n})
    client.patch("/api/projekte/drin", json={"gruppe": g["id"]})
    pfad_alt = Projekt.laden("alt").ordner / "projekt.json"
    daten = json.loads(pfad_alt.read_text(encoding="utf-8"))
    daten.pop("gruppe", None)
    pfad_alt.write_text(json.dumps(daten), encoding="utf-8")
    pfad_w = Projekt.laden("waise").ordner / "projekt.json"
    daten = json.loads(pfad_w.read_text(encoding="utf-8"))
    daten["gruppe"] = "g-deadbeef"
    pfad_w.write_text(json.dumps(daten), encoding="utf-8")

    abschnitte = client.get("/api/projektliste").json()["abschnitte"]
    nach_id = {a["id"]: a for a in abschnitte}
    assert nach_id[leer["id"]]["anzahl"] == 0 and nach_id[leer["id"]]["projekte"] == []
    assert [p["slug"] for p in nach_id[g["id"]]["projekte"]] == ["drin"]
    assert nach_id["ohne"]["titel"] == "Ohne Gruppe" and nach_id["ohne"]["art"] == "ohne"
    assert sorted(p["slug"] for p in nach_id["ohne"]["projekte"]) == ["alt", "waise"]
    assert nach_id["ohne"]["anzahl"] == 2
    # eigene Gruppen nach Name, "Ohne Gruppe" zuletzt
    assert [a["titel"] for a in abschnitte] == ["Leer", "Mathe", "Ohne Gruppe"]


def test_projektliste_gruppe_geloescht_dann_ohne_gruppe(client):
    g = client.post("/api/gruppen", json={"name": "Mathe"}).json()
    client.post("/api/projekte", json={"name": "Eins"})
    client.patch("/api/projekte/eins", json={"gruppe": g["id"]})
    client.delete(f"/api/gruppen/{g['id']}")
    abschnitte = client.get("/api/projektliste").json()["abschnitte"]
    assert [a["id"] for a in abschnitte] == ["ohne"]
    assert [p["slug"] for p in abschnitte[0]["projekte"]] == ["eins"]


def test_projektliste_ungueltige_werte(client):
    assert client.get("/api/projektliste?modus=quatsch").status_code == 400
    assert client.get("/api/projektliste?sortierung=quatsch").status_code == 400


# ---------------------------------------------------------------- US3: Verwalten

def test_api_umbenennen_in_andere_schreibweise_eines_vorhandenen_namens_409(client):
    a = client.post("/api/gruppen", json={"name": "Mathe"}).json()
    client.post("/api/gruppen", json={"name": "Physik"})
    for name in ("PHYSIK", "physik", " Physik "):
        assert client.patch(f"/api/gruppen/{a['id']}", json={"name": name}).status_code == 409
    assert client.get("/api/gruppen").json()[0]["name"] == "Mathe"
    # eigener Name in anderer Schreibweise ist erlaubt
    assert client.patch(f"/api/gruppen/{a['id']}", json={"name": "MATHE"}).status_code == 200


def test_api_mehrere_gruppen_hintereinander_loeschen(client):
    ids = [client.post("/api/gruppen", json={"name": n}).json()["id"] for n in ("A", "B", "C")]
    for i, n in enumerate(("Eins", "Zwei", "Drei")):
        client.post("/api/projekte", json={"name": n})
        client.patch(f"/api/projekte/{n.lower()}", json={"gruppe": ids[i]})
    for gid in ids[:2]:
        assert client.delete(f"/api/gruppen/{gid}").json()["verschoben"] == 1
    assert [g["name"] for g in client.get("/api/gruppen").json()] == ["C"]
    assert client.get("/api/projekte/eins").json()["gruppe"] is None
    assert client.get("/api/projekte/zwei").json()["gruppe"] is None
    assert client.get("/api/projekte/drei").json()["gruppe"] == ids[2]
    assert client.delete(f"/api/gruppen/{ids[2]}").json()["verschoben"] == 1
    abschnitte = client.get("/api/projektliste").json()["abschnitte"]
    assert [a["id"] for a in abschnitte] == ["ohne"]
    assert sorted(p["slug"] for p in abschnitte[0]["projekte"]) == ["drei", "eins", "zwei"]


def test_api_auftrag_blockiert_weder_zuweisung_noch_loeschen_der_gruppe(client):
    from genut.server import JOBS, Job

    g = client.post("/api/gruppen", json={"name": "Mathe"}).json()
    client.post("/api/projekte", json={"name": "Eins"})
    job = Job("eins", "generieren")  # läuft: fertig bleibt False
    JOBS.jobs[job.id] = job
    try:
        assert client.get("/api/projekte/eins").json()["laeuft"] == job.id
        r = client.patch("/api/projekte/eins", json={"gruppe": g["id"]})
        assert r.status_code == 200 and r.json()["gruppe"] == g["id"]
        assert client.delete(f"/api/gruppen/{g['id']}").json() == {"ok": True, "verschoben": 1}
        r = client.get("/api/projekte/eins")
        assert r.json()["gruppe"] is None and r.json()["laeuft"] == job.id
        abschnitte = client.get("/api/projektliste").json()["abschnitte"]
        assert [a["id"] for a in abschnitte] == ["ohne"]
    finally:
        JOBS.jobs.pop(job.id, None)
