import json

import pytest

from genut.patch import ersetzen, finden, loeschen, patch_anwenden, patch_fehler
from genut.pruefer import elemente
from genut.schema import Dokument, Patch, ProjektKopf, TextBlock


def _patch(**kw) -> Patch:
    return Patch.model_validate(kw)


ERSTER = {
    "projekt": {"titel": "Integrale", "untertitel": "SA 1"},
    "neue_themen": [{"ref": "T1", "titel": "Grundlagen", "quelle": "foto",
                     "bloecke": [{"typ": "text", "quelle": "foto", "md": "Hallo"}]}],
    "neue_aufgaben": [{"thema_ref": "T1", "art": "probe", "quelle": "foto", "titel": "A", "angabe_md": "x",
                       "schritte": [{"titel": "s", "quelle": "ki", "bloecke": [{"typ": "text", "quelle": "ki", "md": "y"}]}],
                       "ergebnis": {"md": "1", "check": {"art": "gleich", "ausdruck": "1", "erwartet": "1"}}}],
    "neue_karten": [{"thema_ref": "T1", "quelle": "ki", "vorne_md": "v", "hinten_md": "h"}],
}


def test_erster_patch():
    doc = Dokument(projekt=ProjektKopf(titel="leer"))
    p = _patch(**ERSTER)
    assert patch_fehler(doc, p) == []
    neu = patch_anwenden(doc, p)
    assert doc.projekt.titel == "Integrale"
    t = doc.themen[0]
    assert t.id.startswith("t-") and t.bloecke[0].id.startswith("b-")
    assert doc.aufgaben[0].thema_id == t.id and doc.aufgaben[0].quelle == "ki"  # probe ⇒ ki
    assert doc.aufgaben[0].schritte[0].bloecke[0].id.startswith("b-")
    assert doc.karten[0].thema_id == t.id
    assert neu == {t.bloecke[0].id, doc.aufgaben[0].id, doc.karten[0].id}


def test_zweiter_patch_aendert_bestehendes_nicht(doc):
    vorher = {i: el.model_dump_json() for i, el in elemente(doc).items()}
    titel = doc.projekt.titel
    p = _patch(
        projekt={"titel": "Anders"},
        neue_themen=[{"ref": "N", "titel": "Neu", "quelle": "ki", "bloecke": []}],
        neue_bloecke=[{"thema_id": "t-00000001", "nach_block_id": "b-00000002",
                       "block": {"typ": "text", "quelle": "foto", "md": "eingeschoben"}}],
        neue_aufgaben=[{**ERSTER["neue_aufgaben"][0], "thema_ref": "t-00000002"}],
        neue_karten=[{"thema_ref": "N", "quelle": "ki", "vorne_md": "a", "hinten_md": "b"}],
    )
    assert patch_fehler(doc, p) == []
    neu = patch_anwenden(doc, p)
    nachher = {i: el.model_dump_json() for i, el in elemente(doc).items()}
    for i, js in vorher.items():
        assert nachher[i] == js, f"{i} wurde verändert"
    assert doc.projekt.titel == titel  # Kopf nur beim ersten Lauf
    assert doc.themen[0].bloecke[2].md == "eingeschoben"
    assert len(neu) == 3


def test_referenzfehler(doc):
    p = _patch(neue_bloecke=[{"thema_id": "t-gibtsnicht", "block": {"typ": "text", "quelle": "ki", "md": "x"}}],
               neue_karten=[{"thema_ref": "X9", "quelle": "ki", "vorne_md": "a", "hinten_md": "b"}])
    f = patch_fehler(doc, p)
    assert len(f) == 2


def test_ersetzen_behaelt_id_und_typ(doc):
    ersetzen(doc, "b-00000001", TextBlock(typ="text", quelle="ki", md="neu"))
    art, el, _, _ = finden(doc, "b-00000001")
    assert el.md == "neu" and el.id == "b-00000001" and el.pruefung is None
    with pytest.raises(ValueError):
        ersetzen(doc, "b-00000002", TextBlock(typ="text", quelle="ki", md="falscher typ"))


def test_aufgabe_ersetzen_behaelt_thema(doc):
    a = doc.aufgaben[0].model_copy(deep=True)
    a.thema_id = ""
    a.titel = "neu"
    ersetzen(doc, "a-00000001", a)
    assert doc.aufgaben[0].thema_id == "t-00000001" and doc.aufgaben[0].titel == "neu"


def test_thema_loeschen_nimmt_aufgaben_mit(doc):
    loeschen(doc, "t-00000002")
    assert all(a.thema_id != "t-00000002" for a in doc.aufgaben)
    assert all(k.thema_id != "t-00000002" for k in doc.karten)
    with pytest.raises(KeyError):
        finden(doc, "b-00000011")


def test_projekt_speichern_mit_verlauf(projekt_mit_inhalt):
    p = projekt_mit_inhalt
    doc = p.inhalt()
    doc.projekt.titel = "x"
    p.inhalt_speichern(doc)
    assert len(list((p.ordner / "verlauf").glob("inhalt.*.json"))) == 1
    assert json.loads(p.inhalt_pfad.read_text())["projekt"]["titel"] == "x"
