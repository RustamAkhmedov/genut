"""Import als neues Projekt (research.md R7, R8, R13)."""
import copy
import io
import json
import re
import threading

import pytest
from PIL import Image

from genut.config import laden
from genut.funktionen.austausch.anlegen import alle_herkuenfte, herkunft_lesen, importieren
from genut.funktionen.austausch.einlesen import pruefen
from genut.funktionen.austausch.paket import importierbar
from genut.pipeline import Pipeline, fotos_hinzufuegen
from genut.projekt import Projekt
from genut.schema import GraphBlock, SqlBlock

from .hilfen import bild_data_uri, gutes_paket, paket_html

BILD = "b-00000005"  # einziger Bild-Block der Fixture


@pytest.fixture
def paket(projekt_mit_inhalt):
    return gutes_paket(projekt_mit_inhalt)


@pytest.fixture
def attrappe(monkeypatch):
    """Ersetzt das Prüfen und Bauen; zählt die Aufrufe."""
    aufrufe = []

    def pruefen_bauen(self, ids=None):
        aufrufe.append(self.p.slug)
        return {"status": {}}

    monkeypatch.setattr(Pipeline, "pruefen_bauen", pruefen_bauen)
    return aufrufe


def einspielen(paket, dateiname="datei.html") -> dict:
    return importieren(pruefen(paket_html(paket)), dateiname)


def ordner(projekte) -> list[str]:
    return sorted(d.name for d in projekte.iterdir())


def _ohne_pruefung(obj):
    if isinstance(obj, dict):
        return {k: _ohne_pruefung(v) for k, v in obj.items() if k != "pruefung"}
    if isinstance(obj, list):
        return [_ohne_pruefung(v) for v in obj]
    return obj


def vergleichbar(doc) -> dict:
    """Dokument ohne Prüfstatus und ohne Dateiname/Ausschnitt der Bild-Blöcke."""
    d = _ohne_pruefung(doc.model_dump())
    bloecke = [b for t in d["themen"] for b in t["bloecke"]]
    bloecke += [b for a in d["aufgaben"] for s in a["schritte"] for b in s["bloecke"]]
    for b in bloecke:
        if b["typ"] == "bild":
            del b["foto"], b["bbox"]
    return d


def test_hin_und_zurueck(projekt_mit_inhalt):
    p = projekt_mit_inhalt
    # Graph und SQL auch in einem Aufgabenschritt: ausdruck_js und ergebnis kommen nie aus der Datei
    doc = p.inhalt()
    doc.aufgaben[0].schritte[0].bloecke += [
        GraphBlock(typ="graph", id="b-000000a1", quelle="ki",
                   graph={"x_min": 0, "x_max": 2, "funktionen": [{"ausdruck": "x**2"}]}),
        SqlBlock(typ="sql", id="b-000000a2", quelle="ki",
                 schema_sql="CREATE TABLE t(a INTEGER); INSERT INTO t VALUES (7);", abfrage="SELECT a FROM t"),
    ]
    p.inhalt_speichern(doc)
    Pipeline(p).pruefen_bauen()
    original = p.inhalt()

    r = importieren(pruefen(importierbar(p).encode()), "test-integral.html")

    assert r["slug"] == f"{p.slug}-2" and r["name"] == "Test Integral" and r["warnung"] is None
    assert r["status"] and sum(r["status"].values()) > 0
    neu = Projekt.laden(r["slug"])
    m, alt = neu.meta(), p.meta()
    assert (m.name, m.fach, m.einstellungen) == (alt.name, alt.fach, alt.einstellungen)
    assert m.fotos == [] and m.gruppe is None and m.modell == laden()["modell"]["standard"]
    importiert = neu.inhalt()
    assert vergleichbar(importiert) == vergleichbar(original)
    graph, sql = importiert.aufgaben[0].schritte[0].bloecke[-2:]
    assert graph.graph.funktionen[0].ausdruck_js
    assert sql.ergebnis is not None and sql.ergebnis.zeilen == [[7]]
    (bild,) = [b for t in importiert.themen for b in t.bloecke if b.typ == "bild"]
    assert bild.foto == "import-001.webp" and bild.bbox == [0, 0, 1, 1]
    assert (neu.fotos / "import-001.webp").is_file()
    assert neu.ausgabe.exists() and (neu.fotos / "original").is_dir()


def test_gefaelschtes_ok_wird_fehler(paket):
    aufgabe = next(a for a in paket["inhalt"]["aufgaben"] if (a["ergebnis"].get("check") or {}).get("art") == "gleich")
    aufgabe["ergebnis"]["check"]["erwartet"] = "123456"
    aufgabe["pruefung"] = {"status": "ok", "meldungen": [], "runden": 0, "zeit": ""}
    r = einspielen(paket)
    neu = {a.id: a for a in Projekt.laden(r["slug"]).inhalt().aufgaben}
    assert neu[aufgabe["id"]].pruefung.status == "fehler"
    assert r["status"]["fehler"] >= 1


def test_zweimal_ergibt_neue_ordner(paket, projekte, attrappe):
    assert [einspielen(paket)["slug"] for _ in range(2)] == ["test-integral-2", "test-integral-3"]
    assert attrappe == ["test-integral-2", "test-integral-3"]
    assert ordner(projekte) == ["test-integral", "test-integral-2", "test-integral-3"]


def test_gleichzeitig_zwei_ordner(paket, projekte, attrappe):
    geprueft = [pruefen(paket_html(paket)) for _ in range(2)]
    start, slugs = threading.Barrier(2), []

    def lauf(g):
        start.wait()
        slugs.append(importieren(g, "x.html")["slug"])

    threads = [threading.Thread(target=lauf, args=(g,)) for g in geprueft]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sorted(slugs) == ["test-integral-2", "test-integral-3"]


@pytest.mark.parametrize("ziel", ["genut.projekt.Projekt.inhalt_speichern",
                                  "genut.projekt.Projekt.meta_speichern",
                                  "genut.funktionen.austausch.anlegen.atomar_schreiben"])
def test_schreibfehler_hinterlaesst_nichts(paket, projekte, attrappe, monkeypatch, ziel):
    vorher = ordner(projekte)

    def kaputt(*a, **kw):
        raise OSError("Platte voll")

    g = pruefen(paket_html(paket))
    monkeypatch.setattr(ziel, kaputt)
    with pytest.raises(RuntimeError, match="^Import fehlgeschlagen, es wurde nichts angelegt: Platte voll"):
        importieren(g, "x.html")
    assert ordner(projekte) == vorher and attrappe == []


def test_bauen_scheitert_projekt_bleibt(paket, monkeypatch):
    def kaputt(self, ids=None):
        raise RuntimeError("prerender.js fehlgeschlagen")

    monkeypatch.setattr(Pipeline, "pruefen_bauen", kaputt)
    r = einspielen(paket)
    assert r["status"] == {} and "prerender.js fehlgeschlagen" in r["warnung"]
    assert r["warnung"].startswith("Prüfen/Bauen fehlgeschlagen: ")
    assert Projekt.laden(r["slug"]).hat_inhalt()


@pytest.mark.parametrize("art,daten,name,hinweis", [
    ("datei", bild_data_uri("jpeg", 40, 30), "import-001-b1.jpg", "Bild aus der Datei"),
    ("foto", "", "fehlt-001.webp", "Bild fehlt"),
])
def test_bildarten_in_der_seite(paket, art, daten, name, hinweis):
    paket["bilder"][BILD] = {"art": art, "daten": daten}
    p = Projekt.laden(einspielen(paket)["slug"])
    (bild,) = [b for t in p.inhalt().themen for b in t.bloecke if b.typ == "bild"]
    assert bild.foto == name and (p.fotos / name).is_file() == bool(daten)
    assert hinweis in p.ausgabe.read_text(encoding="utf-8")


def test_eigene_fotos_ergaenzen(paket, attrappe):
    paket["bilder"][BILD] = {"art": "datei", "daten": bild_data_uri("jpeg", 40, 30)}
    p = Projekt.laden(einspielen(paket)["slug"])
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), "white").save(buf, "JPEG")
    (eintrag,) = fotos_hinzufuegen(p, [("neu.jpg", buf.getvalue())])
    assert eintrag.datei == "001.jpg" and p.meta().fotos == [eintrag]


@pytest.mark.parametrize("name,erwartet,slug", [
    ("", "Importiertes Projekt", "importiertes-projekt"),
    ("   ", "Importiertes Projekt", "importiertes-projekt"),
    ("???", "???", "projekt"),
    ("ä" * 200, "ä" * 200, "ae" * 80),  # sonst wäre der Ordnername zu lang fürs Dateisystem
])
def test_namen(paket, attrappe, name, erwartet, slug):
    paket["projekt"]["name"] = name
    r = einspielen(paket)
    assert (r["name"], r["slug"]) == (erwartet, slug)
    assert Projekt.laden(slug).meta().name == erwartet


@pytest.mark.parametrize("roh,erwartet", [
    ("../../etc/Che\x00mie\n\u202e.html", "Chemie.html"),
    ("C:\\Users\\a\\chemie.html", "chemie.html"),
    ("", "unbekannt.html"),
    ("ordner/", "unbekannt.html"),
    ("a" * 300, "a" * 120),
])
def test_herkunft(paket, attrappe, roh, erwartet):
    p = Projekt.laden(einspielen(paket, roh)["slug"])
    h = herkunft_lesen(p)
    assert h.dateiname == erwartet and h.format == 1
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", h.importiert_am)
    assert alle_herkuenfte() == {p.slug: h.model_dump()}


@pytest.mark.parametrize("inhalt", [b"kein json", b'{"importiert_am": "x"}', b"\xff\xfe"])
def test_ungueltige_herkunft_wird_ignoriert(projekt_mit_inhalt, inhalt):
    datei = projekt_mit_inhalt.ordner / "herkunft.json"
    datei.write_bytes(inhalt)
    assert herkunft_lesen(projekt_mit_inhalt) is None and alle_herkuenfte() == {}
    assert datei.read_bytes() == inhalt


# ---------------------------------------------------------------- fremde Inhalte in der Seite (R13, T016)

BOESE = "<script>alert(1)</script> <img src=x onerror=alert(1)> [x](javascript:alert(1))"


def test_fremdes_markup_bleibt_text(paket):
    harmlos = einspielen(copy.deepcopy(paket))
    thema = paket["inhalt"]["themen"][0]
    thema["kurz"] = BOESE
    next(b for b in thema["bloecke"] if b["typ"] == "text")["md"] = BOESE
    paket["inhalt"]["karten"][0]["vorne_md"] = BOESE
    boese = einspielen(paket)
    assert boese["warnung"] is None
    a, b = (Projekt.laden(r["slug"]).ausgabe.read_text(encoding="utf-8") for r in (harmlos, boese))
    # nur echte Tags und Links zählen, maskierter Text (&lt;img …) ist harmlos
    assert not re.search(r"<[a-zA-Z][^<>]*\son\w+\s*=\s*[\"']?alert", b)
    assert not re.search(r"(?:href|src)\s*=\s*[\"']?\s*javascript:", b, re.I)
    assert "<img src=x" not in b and "<script>alert" not in b
    assert len(re.findall(r"<script", b, re.I)) == len(re.findall(r"<script", a, re.I))
