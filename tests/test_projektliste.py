"""Sortierung, Gruppierung und Vollständigkeit der Projektliste (GET /api/projektliste)."""
import time

import pytest

from genut import gruppen
from genut.projekt import Projekt

MODI = ("gruppen", "fach", "keine")
SORTIERUNGEN = ("name", "gebaut", "fach")


@pytest.fixture
def client(projekte):
    from fastapi.testclient import TestClient

    from genut.server import app

    return TestClient(app)


def anlegen(name, fach="mathe", gruppe=None, build=None):
    p = Projekt.anlegen(name, fach=fach)
    if gruppe or build:
        m = p.meta()
        m.gruppe = gruppe
        m.letzter_build = build
        p.meta_speichern(m)
    return p


def liste(client, modus="keine", sortierung="name"):
    r = client.get("/api/projektliste", params={"modus": modus, "sortierung": sortierung})
    assert r.status_code == 200
    return r.json()["abschnitte"]


def namen(abschnitt):
    return [p["name"] for p in abschnitt["projekte"]]


def test_name_ohne_gross_klein_umlaut_und_eszett(client):
    for n in ("zebra", "Äpfel", "Banane", "apfelsaft", "Straße", "strasse x", "Strand", "Ökonomie", "Olive"):
        anlegen(n)
    [a] = liste(client, "keine", "name")
    assert a["id"] == "alle" and a["art"] == "alle"
    assert namen(a) == ["Äpfel", "apfelsaft", "Banane", "Ökonomie", "Olive", "Strand", "Straße", "strasse x", "zebra"]


def test_gebaut_absteigend_ohne_build_am_ende(client):
    anlegen("Alt", build="2026-01-01T10:00:00")
    anlegen("Neu", build="2026-03-01T10:00:00")
    anlegen("Mitte", build="2026-02-01T10:00:00")
    anlegen("Zeta")
    anlegen("alpha")
    [a] = liste(client, "keine", "gebaut")
    assert namen(a) == ["Neu", "Mitte", "Alt", "alpha", "Zeta"]


def test_fach_nach_fachname_dann_name(client):
    anlegen("Zwei", fach="physik")
    anlegen("Eins", fach="physik")
    anlegen("Mathe B", fach="mathe")
    anlegen("Mathe A", fach="mathe")
    anlegen("Deutsch 1", fach="deutsch")
    [a] = liste(client, "keine", "fach")
    # Fachnamen: Deutsch < Mathematik < Physik
    assert namen(a) == ["Deutsch 1", "Mathe A", "Mathe B", "Eins", "Zwei"]


def test_modus_fach_nur_faecher_mit_projekten(client):
    anlegen("P1", fach="physik")
    anlegen("M1", fach="mathe")
    anlegen("M2", fach="mathe")
    ab = liste(client, "fach", "name")
    assert [(a["id"], a["titel"], a["art"], a["anzahl"]) for a in ab] == [
        ("mathe", "Mathematik", "fach", 2), ("physik", "Physik", "fach", 1)]
    assert namen(ab[0]) == ["M1", "M2"]


def test_modus_fach_laesst_eigene_gruppen_unveraendert(client):
    g = gruppen.anlegen("Schularbeit")
    anlegen("Eins", fach="mathe", gruppe=g["id"])
    ab = liste(client, "fach", "name")
    assert [a["id"] for a in ab] == ["mathe"]
    # die Gruppenzuordnung bleibt erhalten, im Modus gruppen erscheint sie wieder
    assert client.get("/api/projekte/eins").json()["gruppe"] == g["id"]
    ab = liste(client, "gruppen", "name")
    assert [a["id"] for a in ab] == [g["id"]]
    assert namen(ab[0]) == ["Eins"]


def test_modus_keine_ein_abschnitt_alle(client):
    g = gruppen.anlegen("Mathe")
    anlegen("A", gruppe=g["id"])
    anlegen("B", fach="physik")
    ab = liste(client, "keine", "name")
    assert len(ab) == 1 and ab[0]["id"] == "alle" and ab[0]["anzahl"] == 2
    assert namen(ab[0]) == ["A", "B"]


def test_standardwerte_gruppen_und_gebaut(client):
    anlegen("Alt", build="2026-01-01T10:00:00")
    anlegen("Neu", build="2026-02-01T10:00:00")
    ab = client.get("/api/projektliste").json()["abschnitte"]
    assert [a["id"] for a in ab] == ["ohne"]
    assert namen(ab[0]) == ["Neu", "Alt"]


@pytest.mark.parametrize("query", [
    "modus=quatsch", "sortierung=quatsch", "modus=&sortierung=name", "modus=GRUPPEN", "modus=fach&sortierung=x",
])
def test_ungueltige_parameter_400(client, query):
    assert client.get(f"/api/projektliste?{query}").status_code == 400


def test_gleichstand_stabil_nach_slug(client):
    # gleicher Name (nur Groß/Klein verschieden bzw. identisch) -> Slug entscheidet
    anlegen("Gleich")
    anlegen("gleich")
    anlegen("Gleich")
    erwartet = sorted(p["slug"] for p in client.get("/api/projekte").json())
    for modus in MODI:
        for sortierung in ("name", "fach"):
            ab = liste(client, modus, sortierung)
            assert [p["slug"] for p in ab[0]["projekte"]] == erwartet
    # gleicher Build-Zeitpunkt -> Slug
    for n in ("Q", "P", "R"):
        anlegen(n, build="2026-05-05T05:05:05")
    [a] = liste(client, "keine", "gebaut")
    mit = [p["slug"] for p in a["projekte"] if p["letzter_build"]]
    assert mit == sorted(mit)


def test_projekt_ohne_gueltiges_fach_im_modus_fach(client):
    p = anlegen("Rest")
    anlegen("Mathe", fach="mathe")
    # Fach "netzwerk" (alter Wert) wird auf nscs abgebildet
    m = p.meta()
    object.__setattr__(m, "fach", "netzwerk")
    p.meta_speichern(m)
    ab = liste(client, "fach", "name")
    assert sorted(sum((namen(a) for a in ab), [])) == ["Mathe", "Rest"]


@pytest.mark.parametrize("modus", MODI)
@pytest.mark.parametrize("sortierung", SORTIERUNGEN)
def test_kein_projekt_fehlt_oder_doppelt(client, modus, sortierung):
    g1 = gruppen.anlegen("Eins")
    g2 = gruppen.anlegen("Zwei")
    gruppen.anlegen("Leer")
    faecher = ["mathe", "physik", "deutsch", "sonstiges"]
    for i in range(24):
        anlegen(f"Projekt {i % 7} {'äß' if i % 3 else 'x'}", fach=faecher[i % 4],
                gruppe=(g1["id"], g2["id"], "g-deadbeef", None)[i % 4],
                build=f"2026-0{1 + i % 5}-01T00:00:00" if i % 2 else None)
    alle = sorted(p["slug"] for p in client.get("/api/projekte").json())
    assert len(alle) == 24
    ab = liste(client, modus, sortierung)
    gesehen = [p["slug"] for a in ab for p in a["projekte"]]
    assert sorted(gesehen) == alle
    assert all(a["anzahl"] == len(a["projekte"]) for a in ab)


def test_100_projekte_in_20_gruppen_unter_einer_sekunde(client):
    ids = [gruppen.anlegen(f"Gruppe {i:02d}")["id"] for i in range(20)]
    for i in range(100):
        anlegen(f"Projekt {i:03d}", gruppe=ids[i % 20], build=f"2026-01-{1 + i % 28:02d}T00:00:00")
    for modus in MODI:
        start = time.perf_counter()
        ab = liste(client, modus, "gebaut")
        dauer = time.perf_counter() - start
        assert sum(a["anzahl"] for a in ab) == 100
        assert dauer < 1.0, f"{modus}: {dauer:.2f}s"
