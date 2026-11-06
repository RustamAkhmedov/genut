"""Mengen je Thema nachzählen und einmal gezielt nachfordern."""
import json

from genut.modelle.base import ModellFehler
from genut.pipeline import Pipeline, fotos_hinzufuegen, mengen_fehlen
from genut.projekt import Projekt
from genut.schema import Dokument, Einstellungen
from tests.conftest import FIX
from tests.test_pipeline import FakeModell


def frage(ref, n):
    return {"thema_ref": ref, "quelle": "ki", "art": "wahrfalsch", "frage_md": f"Aussage {n}", "optionen": [],
            "wahr": True, "erklaerung_md": "weil"}


def karte(ref, n):
    return {"thema_ref": ref, "quelle": "ki", "vorne_md": f"Frage {n}", "hinten_md": "Antwort"}


def probe(ref, n):
    return {"thema_ref": ref, "art": "probe", "quelle": "ki", "titel": f"Probe {n}", "angabe_md": "Erkläre.",
            "schritte": [{"titel": "Lösung", "quelle": "ki", "bloecke": [{"typ": "text", "quelle": "ki", "md": "So."}]}],
            "ergebnis": {"md": "Fertig."}}


def thema(ref="T1", bloecke=True):
    return {"ref": ref, "titel": f"Thema {ref}", "quelle": "foto",
            "bloecke": [{"typ": "text", "quelle": "foto", "foto": "001.jpg", "md": "Inhalt"}] if bloecke else []}


def voll(ref="T1", fragen=2, karten=3, proben=1):
    return {"neue_aufgaben": [probe(ref, i) for i in range(proben)], "neue_karten": [karte(ref, i) for i in range(karten)],
            "neue_fragen": [frage(ref, i) for i in range(fragen)]}


def projekt(fragen=2, proben=1, karten="auto"):
    p = Projekt.anlegen("Nachfordern")
    fotos_hinzufuegen(p, [("heft.jpg", (FIX / "fotos" / "001.jpg").read_bytes())])
    m = p.meta()
    m.einstellungen = Einstellungen(quiz_pro_thema=fragen, probeaufgaben_pro_thema=proben, karten=karten)
    m.fotos[0].status = "kontrolliert"
    p.meta_speichern(m)
    p.transkript_speichern("001.jpg", "# Heft\nInhalt")
    return p


def test_mengen_fehlen_zaehlregeln():
    from genut.patch import patch_anwenden
    from genut.schema import Patch, ProjektKopf
    doc = Dokument(projekt=ProjektKopf(titel="x", fach="englisch"))
    vokabel = {"typ": "vokabel", "quelle": "foto", "wort": "dog", "uebersetzung": "Hund"}
    patch_anwenden(doc, Patch.model_validate({
        "neue_themen": [{**thema("T1"), "bloecke": [vokabel, vokabel]}, thema("T2", bloecke=False)],
        "neue_karten": [karte("T1", 0)], "neue_fragen": [frage("T1", 0), frage("T2", 0)]}))
    t1, t2 = (t.id for t in doc.themen)
    e = Einstellungen(quiz_pro_thema=2, probeaufgaben_pro_thema=0, karten="auto")
    fehlt = mengen_fehlen(doc, {t1, t2}, e)
    assert fehlt[t1] == ["1 Quizfrage(n)"]                       # 1 Karte + 2 Vokabeln = 3 Karten, reicht für „auto“
    assert fehlt[t2][0].startswith("Inhaltsblöcke") and "3 Karteikarte(n)" in fehlt[t2]
    assert mengen_fehlen(doc, {t1}, Einstellungen(quiz_pro_thema=1, probeaufgaben_pro_thema=0, karten=3)) == {}
    assert mengen_fehlen(doc, {t1}, Einstellungen(quiz_pro_thema=1, probeaufgaben_pro_thema=0, karten=4)) == {
        t1: ["1 Karteikarte(n)"]}
    assert mengen_fehlen(doc, set(), e) == {}                    # nur die übergebenen (neuen) Themen zählen


def test_nichts_fehlt_kein_zweiter_aufruf(projekte):
    p = projekt()
    m = FakeModell(jsons=[{"neue_themen": [thema()], **voll()}])
    z = Pipeline(p, modell=m).generieren()
    assert len(m.prompts) == 1 and z["nachgefordert"] is False and z["fehlt"] == {}


def test_fehlendes_wird_gezielt_nachgefordert(projekte):
    p = projekt(fragen=3, proben=2)
    erste = {"neue_themen": [thema()], **voll(fragen=1, karten=1, proben=1)}
    m = FakeModell(jsons=[erste])
    pl = Pipeline(p, modell=m)
    orig = m.json

    def antwort(prompt, schema, bilder):
        if "## Auftrag: Fehlende Inhalte nachliefern" in prompt:
            m.prompts.append(prompt)
            tid = p.inhalt().themen[0].id
            return {"neue_aufgaben": [probe(tid, 9)], "neue_karten": [karte(tid, 8), karte(tid, 9)],
                    "neue_fragen": [frage(tid, 8), frage(tid, 9)]}
        return orig(prompt, schema, bilder)

    m.json = antwort
    z = pl.generieren()
    nach = m.prompts[1]
    tid = p.inhalt().themen[0].id
    assert f"Thema `{tid}` (Thema T1): es fehlen 1 Probeaufgabe(n), 2 Karteikarte(n), 2 Quizfrage(n)" in nach
    assert "schon vorhanden (nicht wiederholen): Aussage 0 | Frage 0" in nach
    assert "<transkript" in nach and "Lege **keine** neuen Themen an" in nach
    doc = p.inhalt()
    assert len(doc.quiz) == 3 and len(doc.karten) == 3 and len(doc.aufgaben) == 2
    assert z["nachgefordert"] is True and z["fehlt"] == {} and z["neu"] == 1 + 3 + 5   # Block + erste Antwort + Nachforderung


def test_ungefragte_neue_themen_werden_verworfen(projekte):
    p = projekt(fragen=2, proben=0)
    m = FakeModell(jsons=[{"neue_themen": [thema()], **voll(fragen=1, proben=0)}])
    orig = m.json

    def antwort(prompt, schema, bilder):
        if "## Auftrag: Fehlende Inhalte nachliefern" in prompt:
            tid = p.inhalt().themen[0].id
            return {"neue_themen": [thema("X")], "neue_fragen": [frage(tid, 5), frage("X", 6)],
                    "projekt": {"titel": "Anderer Titel"}}
        return orig(prompt, schema, bilder)

    m.json = antwort
    z = Pipeline(p, modell=m).generieren()
    doc = p.inhalt()
    assert [t.titel for t in doc.themen] == ["Thema T1"] and len(doc.quiz) == 2
    assert doc.projekt.titel == "Nachfordern" and z["fehlt"] == {}


def test_nachfordern_scheitert_seite_bleibt(projekte):
    p = projekt(fragen=4)
    m = FakeModell(jsons=[{"neue_themen": [thema()], **voll(fragen=1)}])
    orig = m.json
    meldungen = []

    def antwort(prompt, schema, bilder):
        if "## Auftrag: Fehlende Inhalte nachliefern" in prompt:
            raise ModellFehler("Gemini: Tageslimit des Gratis-Kontingents bei allen Flash-Modellen erreicht")
        return orig(prompt, schema, bilder)

    m.json = antwort
    z = Pipeline(p, modell=m, log=lambda art, **k: meldungen.append(k.get("text", ""))).generieren()
    tid = p.inhalt().themen[0].id
    assert z["nachgefordert"] is True and z["fehlt"] == {tid: ["3 Quizfrage(n)"]}
    assert any("Nachfordern fehlgeschlagen" in t for t in meldungen)
    assert p.ausgabe.exists() and p.meta().fotos[0].status == "verarbeitet"


def test_log_nennt_echtes_gemini_modell(projekte, monkeypatch):
    from genut.modelle import gemini as gm
    g = gm.Gemini({"modell": ""})
    g._liste, g._nr, g.gruende = ["gemini-3.8-flash", "gemini-3-flash-preview"], 1, {"gemini-3.8-flash": 503}
    assert g.info() == {"modell": "gemini-3-flash-preview", "fehler": {"gemini-3.8-flash": 503}}
    assert gm.Gemini({"modell": ""}).info() == {"modell": None, "fehler": {}}   # ohne Netzwerkzugriff
    monkeypatch.setattr(g, "text", lambda prompt, bilder: "# Heft")
    p = projekt()
    m = p.meta(); m.fotos[0].status = "hochgeladen"; p.meta_speichern(m)
    meldungen = []
    Pipeline(p, modell=g, log=lambda art, **k: meldungen.append(k.get("text", ""))).transkribieren()
    log = json.loads(next(p.logs.glob("*transkribieren.json")).read_text(encoding="utf-8"))
    assert log["modell_info"]["modell"] == "gemini-3-flash-preview"
    assert any(t.endswith("(gemini-3-flash-preview)") for t in meldungen)
