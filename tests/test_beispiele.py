"""Prompt-Verbesserungen für Gemini: Beispiel-Patches je Profil, box_2d-Skizzen, Transkript-Tags, Temperatur."""
import json

import jsonschema
import pytest

from genut import faecher
from genut.config import PAKET
from genut.patch import patch_anwenden, patch_fehler
from genut.pipeline import Pipeline, beispiel_text, box_2d_umrechnen, fotos_hinzufuegen
from genut.projekt import Projekt
from genut.pruefer import pruefe
from genut.schema import Dokument, Patch, ProjektKopf, ki_schema
from tests.conftest import FIX
from tests.test_pipeline import FakeModell

BEISPIELE = PAKET / "prompts" / "beispiele"


def _bloecke(obj):
    """Alle Blocktypen und Check-Arten im Beispiel (rekursiv)."""
    typen, checks = set(), set()
    if isinstance(obj, dict):
        if "typ" in obj and "quelle" in obj:
            typen.add(obj["typ"])
        if "check" in obj and obj["check"]:
            checks.add(obj["check"]["art"])
        for v in obj.values():
            t, c = _bloecke(v)
            typen |= t; checks |= c
    elif isinstance(obj, list):
        for v in obj:
            t, c = _bloecke(v)
            typen |= t; checks |= c
    return typen, checks


def test_jedes_profil_hat_ein_beispiel():
    assert {p.stem for p in BEISPIELE.glob("*.json")} == set(faecher.PROFILE)


@pytest.mark.parametrize("fach", sorted(faecher.FAECHER))
def test_beispiel_passt_zum_schema_des_fachs(fach):
    roh = json.loads((BEISPIELE / f"{faecher.profil_von(fach)}.json").read_text(encoding="utf-8"))
    jsonschema.validate(roh, ki_schema(Patch, fach))          # so, wie Gemini es angeboten bekommt
    typen, checks = _bloecke(roh)
    assert typen <= faecher.erlaubte_bloecke(fach)
    assert checks <= faecher.profil(fach).checks


@pytest.mark.parametrize("profil", sorted(faecher.PROFILE))
def test_beispiel_besteht_den_pruefer(profil):
    fach = next(k for k, f in faecher.FAECHER.items() if f.profil == profil)
    patch = Patch.model_validate_json((BEISPIELE / f"{profil}.json").read_text(encoding="utf-8"))
    doc = Dokument(projekt=ProjektKopf(titel="Test", fach=fach))
    assert patch_fehler(doc, patch) == []
    ids = patch_anwenden(doc, patch)
    ergebnis = pruefe(doc, ids, None)
    fehler = {i: pr.meldungen for i, pr in ergebnis.items() if pr.status == "fehler"}
    assert not fehler


def test_beispiel_text():
    t = beispiel_text("datenbanken")
    assert t.startswith("## Beispiel (nur fürs Format)") and "HAVING COUNT(*) > 2" in t
    assert beispiel_text("gibt_es_nicht") == ""


@pytest.mark.parametrize("ein,aus", [
    ('[[SKIZZE art=graph box_2d=100,200,600,900 beschreibung="Parabel"]]',
     '[[SKIZZE art=graph bbox=0.2,0.1,0.7,0.5 beschreibung="Parabel"]]'),
    ('[[SKIZZE art=bild box_2d=[0, 0, 1000, 1000] beschreibung="x"]]', '[[SKIZZE art=bild bbox=0,0,1,1 beschreibung="x"]]'),
    ('[[SKIZZE art=bild box_2d=600,900,100,200 beschreibung="vertauscht"]]',
     '[[SKIZZE art=bild bbox=0.2,0.1,0.7,0.5 beschreibung="vertauscht"]]'),
    ('[[SKIZZE art=bild box_2d=-5,0,1200,333 beschreibung="x"]]', '[[SKIZZE art=bild bbox=0,0,0.333,1 beschreibung="x"]]'),
    ("Text mit box_2d=1,2,3,4 ohne Skizze", "Text mit box_2d=1,2,3,4 ohne Skizze"),
    ('[[SKIZZE art=bild bbox=0.1,0.2,0.3,0.4 beschreibung="alt"]]', '[[SKIZZE art=bild bbox=0.1,0.2,0.3,0.4 beschreibung="alt"]]'),
])
def test_box_2d_umrechnen(ein, aus):
    assert box_2d_umrechnen(ein) == aus


class FakeGemini(FakeModell):
    name = "gemini"
    bbox_format = "box_2d"
    beispiele = True


def _projekt():
    p = Projekt.anlegen("Prompt Test")
    fotos_hinzufuegen(p, [("heft.jpg", (FIX / "fotos" / "001.jpg").read_bytes())])
    return p


def test_gemini_bekommt_box_2d_und_beispiel(projekte):
    p = _projekt()
    m = FakeGemini(texte=['# Heft\n[[SKIZZE art=graph box_2d=100,200,600,900 beschreibung="Parabel"]]'],
                   jsons=[{"neue_themen": [{"ref": "T1", "titel": "A", "quelle": "foto"}]}])
    pl = Pipeline(p, modell=m)
    pl.transkribieren()
    assert "box_2d=ymin,xmin,ymax,xmax" in m.prompts[0] and "bbox=x,y,b,h" not in m.prompts[0]
    assert "{{skizze_format}}" not in m.prompts[0]
    assert "bbox=0.2,0.1,0.7,0.5" in p.transkript("001.jpg")       # gespeichert wird immer bbox
    pl.foto_status("001.jpg", "kontrolliert")
    pl.generieren()
    prompt = m.prompts[1]
    assert '<transkript datei="001.jpg">\n# Heft' in prompt and "</transkript>" in prompt
    assert "## Beispiel (nur fürs Format)" in prompt and "{{beispiel}}" not in prompt


def test_andere_kis_unveraendert(projekte):
    p = _projekt()
    m = FakeModell(texte=["# Heft </transkript> Ende"], jsons=[{"neue_themen": [{"ref": "T1", "titel": "A", "quelle": "foto"}]}])
    pl = Pipeline(p, modell=m)
    pl.transkribieren()
    assert "bbox=x,y,b,h" in m.prompts[0] and "box_2d" not in m.prompts[0]
    pl.foto_status("001.jpg", "kontrolliert")
    pl.generieren()
    prompt = m.prompts[1]
    assert "## Beispiel" not in prompt and "{{beispiel}}" not in prompt
    assert prompt.count("</transkript>") == 1 and "&lt;/transkript&gt;" in prompt   # kein vorzeitiges Ende


@pytest.mark.parametrize("modell,temp", [("gemini-3.8-flash", None), ("gemini-2.5-flash", 0.2),
                                         ("gemini-flash-latest", None)])
def test_gemini_temperatur(modell, temp):
    from genut.modelle.gemini import _konfig
    k = _konfig(modell, {"responseMimeType": "application/json"})
    assert k.get("temperature") == temp and k["responseMimeType"] == "application/json"
