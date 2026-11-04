"""Pipeline mit einem Fake-Modell: Korrekturschleife (M3) und Fotos ergänzen (M5)."""
import shutil

from genut.pipeline import Pipeline, fotos_hinzufuegen
from genut.projekt import Projekt
from genut.pruefer import elemente
from tests.conftest import FIX


class FakeModell:
    name = "fake"

    def __init__(self, texte=(), jsons=()):
        self.texte, self.jsons = list(texte), list(jsons)
        self.prompts = []

    def text(self, prompt, bilder):
        self.prompts.append(prompt)
        return self.texte.pop(0)

    def json(self, prompt, schema, bilder):
        self.prompts.append(prompt)
        return self.jsons.pop(0)


def aufgabe(erwartet, titel="Fläche"):
    return {"art": "foto", "quelle": "foto", "foto": "001.jpg", "titel": titel, "angabe_md": r"\(\int_0^2 x^2\,dx\)",
            "schritte": [{"titel": "Stammfunktion", "quelle": "ki", "bloecke": [{"typ": "text", "quelle": "ki", "md": r"\(x^3/3\)"}]}],
            "ergebnis": {"md": erwartet, "check": {"art": "gleich", "ausdruck": "integrate(x**2, (x, 0, 2))", "erwartet": erwartet}}}


def projekt(projekte):
    p = Projekt.anlegen("Pipeline Test")
    fotos_hinzufuegen(p, [("heft.jpg", (FIX / "fotos" / "001.jpg").read_bytes())])
    return p


def test_ganzer_lauf_mit_korrektur(projekte):
    p = projekt(projekte)
    patch = {"projekt": {"titel": "Integrale"},
             "neue_themen": [{"ref": "T1", "titel": "Fläche", "quelle": "foto",
                              "bloecke": [{"typ": "formel", "quelle": "foto", "tex": r"\int_a^b f\,dx", "spick": True}]}],
             "neue_aufgaben": [{**aufgabe("4/3"), "thema_ref": "T1"}],
             "neue_karten": [{"thema_ref": "T1", "quelle": "ki", "vorne_md": "?", "hinten_md": "!"}]}
    m = FakeModell(texte=["# Heft\n\\(x^2\\)"], jsons=[patch, None])
    pl = Pipeline(p, modell=m)
    pl.transkribieren()
    assert p.transkript("001.jpg").startswith("# Heft")
    pl.foto_status("001.jpg", "kontrolliert")
    aid = None

    # die Korrektur-Antwort braucht die vergebene ID → nachträglich einsetzen
    orig = m.json

    def json_mit_id(prompt, schema, bilder):
        nonlocal aid
        if "Fehlerhafte Elemente" in prompt:
            aid = p.inhalt().aufgaben[0].id
            assert "SymPy berechnet 8/3" in prompt
            return {"aufgaben": [{"id": aid, "aufgabe": aufgabe("8/3")}]}
        return orig(prompt, schema, bilder)

    m.json = json_mit_id
    z = pl.generieren()
    assert z["runden"] == 1
    doc = p.inhalt()
    assert doc.aufgaben[0].id == aid and doc.aufgaben[0].pruefung.status == "ok"
    assert doc.aufgaben[0].thema_id == doc.themen[0].id
    assert p.meta().fotos[0].status == "verarbeitet"
    assert p.ausgabe.exists()


def test_ungueltige_antwort_wird_einmal_wiederholt(projekte):
    p = projekt(projekte)
    p.transkript_speichern("001.jpg", "x")
    gut = {"neue_themen": [{"ref": "T1", "titel": "A", "quelle": "foto", "bloecke": []}]}
    m = FakeModell(jsons=[{"neue_themen": [{"titel": "ohne ref"}]}, gut])
    pl = Pipeline(p, modell=m)
    pl.foto_status("001.jpg", "kontrolliert")
    pl.generieren()
    assert "Deine letzte Antwort war ungültig" in m.prompts[-1]
    assert p.inhalt().themen[0].titel == "A"


def test_fotos_ergaenzen_aendert_bestand_nicht(projekte):
    p = Projekt.anlegen("Ergänzen")
    shutil.copy(FIX / "fotos" / "001.jpg", p.fotos / "001.jpg")
    from genut.schema import Dokument
    doc = Dokument.model_validate_json((FIX / "inhalt.json").read_text())
    p.inhalt_speichern(doc)
    m0 = p.meta()
    from genut.schema import FotoEintrag
    m0.fotos.append(FotoEintrag(datei="001.jpg", original="alt.jpg", status="verarbeitet"))
    p.meta_speichern(m0)
    Pipeline(p).pruefen_bauen()
    vorher = {i: el.model_dump_json() for i, el in elemente(p.inhalt()).items()}

    neu = fotos_hinzufuegen(p, [("neu.png", (FIX / "fotos" / "001.jpg").read_bytes())])
    assert neu[0].datei == "002.jpg"
    patch = {"neue_bloecke": [{"thema_id": "t-00000002", "block": {"typ": "definition", "quelle": "foto", "foto": "002.jpg", "begriff": "Bogen", "md": "Kurvenstück"}}]}
    m = FakeModell(texte=["Bogen = Kurvenstück"], jsons=[patch])
    pl = Pipeline(p, modell=m)
    assert pl.transkribieren() == ["002.jpg"]            # nur das neue Foto
    pl.foto_status("002.jpg", "kontrolliert")
    pl.generieren()
    assert "t-00000002" in m.prompts[-1]                  # Bestand im Prompt
    nachher = {i: el.model_dump_json() for i, el in elemente(p.inhalt()).items()}
    for i, js in vorher.items():
        assert nachher[i] == js, f"{i} verändert"
    assert len(nachher) == len(vorher) + 1
