"""Fach-Profile: Prüfer-Status, Schema-Filter, Quiz-Patch und Browser-Test je Profil-Fixture."""
import json
from pathlib import Path

import pytest

from genut import faecher
from genut.patch import patch_anwenden, patch_fehler
from genut.pruefer import elemente, pruefe
from genut.render.renderer import rendern
from genut.schema import Dokument, Patch, ki_schema

FIX = Path(__file__).parent / "fixtures"
PROFILE = ["naturwiss", "programmieren", "datenbanken", "netzwerk", "sprachen", "wissen"]


def laden(name: str) -> Dokument:
    return Dokument.model_validate_json((FIX / name / "inhalt.json").read_text(encoding="utf-8"))


def _absichtlich_falsch(doc: Dokument) -> set[str]:
    """IDs der Elemente, deren Titel/Ort „Absichtlich falsch“ enthält (gewollte Testfälle)."""
    out = set()
    for i, el in elemente(doc).items():
        if "Absichtlich falsch" in el.model_dump_json() or "Falsche Einheit" in el.model_dump_json():
            out.add(i)
    return out


@pytest.mark.parametrize("name", PROFILE)
def test_pruefstatus(name):
    doc = laden(name)
    erg = pruefe(doc, set(elemente(doc)))
    fehler = {i for i, p in erg.items() if p.status == "fehler"}
    assert fehler == _absichtlich_falsch(doc), {i: erg[i].meldungen for i in fehler ^ _absichtlich_falsch(doc)}


def test_fach_checks_ok():
    doc = laden("naturwiss")
    erg = pruefe(doc, {"a-00000101", "a-00000102", "b-00000102", "b-00000106", "b-00000107", "b-00000108",
                       "q-00000101", "q-00000103"})
    assert all(p.status == "ok" for p in erg.values()), erg
    doc = laden("datenbanken")
    pruefe(doc, {"b-00000302"})
    b = doc.themen[0].bloecke[1]
    assert b.ergebnis.spalten == ["klasse", "anzahl"] and b.ergebnis.zeilen == [["4A", 2], ["4B", 2]]


def test_ohne_pruefart_keine_warnung():
    """Programmieren/Sprachen haben keine Check-Arten → Aufgaben ohne check sind nicht „⚠ ungeprüft“."""
    for name in ("programmieren", "sprachen"):
        doc = laden(name)
        erg = pruefe(doc, {a.id for a in doc.aufgaben})
        assert all(p.status == "ungeprueft" for p in erg.values())


def test_ki_schema_nach_fach():
    pos = json.dumps(ki_schema(Patch, "pos"))
    assert "CodeBlock" in pos and "GraphBlock" not in pos and "CheckGleich" not in pos and "SqlBlock" not in pos
    dbi = json.dumps(ki_schema(Patch, "dbi"))
    assert "SqlBlock" in dbi and "CheckSql" in dbi and "CheckGleich" not in dbi
    chemie = json.dumps(ki_schema(Patch, "chemie"))
    assert "ReaktionBlock" in chemie and "CheckReaktion" in chemie and "CheckEinheit" in chemie
    assert "StrukturBlock" in chemie and "StrukturBlock" not in json.dumps(ki_schema(Patch, "physik"))
    assert len(json.dumps(ki_schema(Patch))) > len(pos)


def test_faecher_und_alte_werte():
    assert faecher.profil_von("nscs") == "netzwerk" and faecher.profil_von("netzwerk") == "netzwerk"
    doc = Dokument.model_validate({"projekt": {"titel": "x", "fach": "netzwerk"}})
    assert doc.projekt.fach == "nscs"
    assert {f["key"] for f in faecher.liste()} >= {"mathe", "physik", "chemie", "pos", "wmc", "dsai", "dbi", "nscs",
                                                   "englisch", "deutsch", "geographie", "syp"}
    for p in faecher.PROFILE:
        assert (Path(faecher.__file__).parent / "prompts" / "profile" / f"{p}.md").exists()


def test_patch_mit_quiz():
    doc = laden("wissen")
    vorher = {q.id: q.model_dump_json() for q in doc.quiz}
    patch = Patch.model_validate({
        "neue_fragen": [
            {"thema_ref": "t-00000601", "quelle": "ki", "art": "wahrfalsch", "frage_md": "Wien liegt in Österreich.",
             "wahr": True, "erklaerung_md": "Ja."},
        ]})
    assert patch_fehler(doc, patch) == []
    neu = patch_anwenden(doc, patch)
    (qid,) = neu
    assert qid.startswith("q-") and len(doc.quiz) == len(vorher) + 1
    assert all(doc.quiz[i].model_dump_json() == v for i, v in enumerate(vorher.values()))
    falsch = Patch.model_validate({"neue_fragen": [{"thema_ref": "T9", "quelle": "ki", "art": "wahrfalsch",
                                                    "frage_md": "x", "wahr": True, "erklaerung_md": "y"}]})
    assert patch_fehler(doc, falsch)


@pytest.mark.parametrize("name", PROFILE)
def test_profil_seite_im_browser(name, tmp_path):
    shot = pytest.importorskip("tests.shot")
    if shot.browser_pfad() is None:
        pytest.skip("kein Chrome/Chromium gefunden")
    doc = laden(name)
    pruefe(doc, set(elemente(doc)))
    ziel = tmp_path / "index.html"
    info = rendern(doc, None, name, ziel)
    assert "TeX-Fehler: 0" in info["log"]
    h = ziel.read_text(encoding="utf-8")
    assert f'data-profil="{faecher.profil_von(doc.projekt.fach)}"' in h
    assert shot.pruefen(ziel) == []


def test_api_faecher_und_quiz(projekte):
    from fastapi.testclient import TestClient

    from genut.projekt import Projekt
    from genut.server import app

    c = TestClient(app)
    assert any(f["key"] == "dbi" and f["profil"] == "datenbanken" for f in c.get("/api/faecher").json())
    assert c.post("/api/projekte", json={"name": "X", "fach": "quatsch"}).status_code == 400
    r = c.post("/api/projekte", json={"name": "SQL Test", "fach": "dbi", "einstellungen": {"quiz_pro_thema": 7}})
    assert r.status_code == 200 and r.json()["fach"] == "dbi" and r.json()["einstellungen"]["quiz_pro_thema"] == 7
    p = Projekt.laden(r.json()["slug"])
    p.inhalt_speichern(laden("datenbanken"))
    assert c.get(f"/api/projekte/{p.slug}").json()["zahlen"]["quiz"] == 2
    assert c.get(f"/api/projekte/{p.slug}/elemente/q-00000301").json()["element"]["art"] == "mc"
    assert c.delete(f"/api/projekte/{p.slug}/elemente/q-00000301").status_code == 200
    assert len(p.inhalt().quiz) == 1


def test_diagramm_api(projekte):
    """Vorschau zeichnet Mermaid → SVG wird bereinigt gespeichert und beim Bauen eingebettet."""
    from fastapi.testclient import TestClient

    from genut.projekt import Projekt
    from genut.server import app

    c = TestClient(app)
    slug = c.post("/api/projekte", json={"name": "Diagramme", "fach": "pos"}).json()["slug"]
    p = Projekt.laden(slug)
    p.inhalt_speichern(laden("programmieren"))
    offen = c.get(f"/api/projekte/{slug}/diagramme/offen").json()
    assert len(offen) == 1 and offen[0]["quelle"].startswith("classDiagram")
    h = offen[0]["hash"]
    boese = ('<svg viewBox="0 0 400 100" style="max-width: 400px;" onload="alert(1)"><script>alert(2)</script>'
             '<a href="javascript:alert(3)"><text>Zaehler</text></a></svg>')
    assert c.put(f"/api/projekte/{slug}/diagramme/{h}", json={"hell": boese, "dunkel": boese}).status_code == 200
    assert c.put(f"/api/projekte/{slug}/diagramme/0000", json={"hell": boese}).status_code == 404
    assert c.put(f"/api/projekte/{slug}/diagramme/{h}", json={"hell": "kein svg"}).status_code == 400
    assert c.get(f"/api/projekte/{slug}/diagramme/offen").json() == []
    assert c.post(f"/api/projekte/{slug}/neu_bauen").status_code == 200
    seite = p.ausgabe.read_text(encoding="utf-8")
    teil = seite.split('class="dg-svg dg-hell">')[1][:400]
    assert "Zaehler" in teil and "<script" not in teil and "onload" not in teil and "javascript:" not in teil
    assert "min-width:260px" in teil


@pytest.mark.parametrize("fach", sorted(faecher.FAECHER))
def test_ki_schema_ist_gueltiges_json_schema(fach):
    """Die Claude-API lehnt ungültige Schemas ab (z. B. leere oneOf-Listen, wenn ein Fach keine Check-Arten hat)."""
    jsonschema = pytest.importorskip("jsonschema")
    from genut.schema import Korrektur, NeuAufgabe, NeuBlock, NeuFrage, NeuKarte
    for modell in (Patch, Korrektur, NeuBlock, NeuAufgabe, NeuKarte, NeuFrage):
        schema = ki_schema(modell, fach)
        jsonschema.Draft202012Validator.check_schema(schema)
        text = json.dumps(schema)
        assert '"anyOf": []' not in text and '"oneOf": []' not in text, (fach, modell.__name__)
