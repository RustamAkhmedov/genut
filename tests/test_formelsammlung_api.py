import re
from pathlib import Path

import pytest

from genut import formelsammlung as fs

WURZEL = Path(__file__).resolve().parent.parent
F1, F2 = "b-00000003", "b-00000011"  # Formeln in tests/fixtures/integral
TITEL1 = "Hauptsatz der Differential- und Integralrechnung"
TITEL2 = "Bogenlänge"  # steht auch als Themenüberschrift, wenn F2 gewählt ist


@pytest.fixture
def client(projekte):
    from fastapi.testclient import TestClient

    from genut.server import app

    return TestClient(app)


@pytest.fixture
def slug(projekt_mit_inhalt):
    return projekt_mit_inhalt.slug


def _url(slug, ende):
    return f"/api/projekte/{slug}/{ende}"


def _eintrag(block_id):
    return {"block_id": block_id, "variablen": True, "erklaerung": False}


def _braucht_pdfkit():
    if not (WURZEL / "node_modules" / "pdfkit").exists():
        pytest.skip("node_modules/pdfkit fehlt (npm install)")


# ------------------------------------------------------------------ Liste und Auswahl

def test_formeln_themen_auswahl_und_kein_pdf(client, slug):
    r = client.get(_url(slug, "formeln"))
    assert r.status_code == 200
    d = r.json()
    assert [[f["id"] for f in t["formeln"]] for t in d["themen"]] == [[F1], [F2]]
    f = d["themen"][0]["formeln"][0]
    assert f["titel"] == TITEL1 and f["tex"] and f["spick"] is True
    assert {"variablen", "hat_erklaerung", "erklaerung_md", "pruefung"} <= set(f)
    assert [e["block_id"] for e in d["auswahl"]] == [F1, F2]  # Standard: Spickzettel-Formeln
    assert d["pdf"] is None


def test_formeln_unbekanntes_projekt_404(client, projekte):
    assert client.get(_url("gibt-es-nicht", "formeln")).status_code == 404


def test_auswahl_speichern_und_lesen(client, slug):
    r = client.put(_url(slug, "formelauswahl"), json={"eintraege": [_eintrag(F2)]})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "gespeichert": 1}
    auswahl = client.get(_url(slug, "formeln")).json()["auswahl"]
    assert [e["block_id"] for e in auswahl] == [F2]


def test_auswahl_unbekannte_kennung_400(client, slug):
    r = client.put(_url(slug, "formelauswahl"), json={"eintraege": [_eintrag("b-99999999")]})
    assert r.status_code == 400
    assert "b-99999999" in r.json()["detail"]
    # Kein Formel-Block (Text-Block) ist ebenfalls unbekannt
    r = client.put(_url(slug, "formelauswahl"), json={"eintraege": [_eintrag("b-00000001")]})
    assert r.status_code == 400


# ------------------------------------------------------------------ Fehlerfälle ohne Node

def test_erzeugen_ohne_gewaehlte_formel_400(client, slug):
    client.put(_url(slug, "formelauswahl"), json={"eintraege": []})
    r = client.post(_url(slug, "formelsammlung"))
    assert r.status_code == 400
    assert "Keine Formel" in r.json()["detail"]


def test_erzeugen_unbekanntes_projekt_404(client, projekte):
    assert client.post(_url("gibt-es-nicht", "formelsammlung")).status_code == 404


def test_pdf_vor_erzeugung_404(client, slug):
    assert client.get(_url(slug, "formelsammlung.pdf")).status_code == 404


def test_erzeugen_laeuft_schon_409(client, projekt_mit_inhalt, slug):
    sperre = fs._sperre(projekt_mit_inhalt)
    assert sperre.acquire(blocking=False)
    try:
        r = client.post(_url(slug, "formelsammlung"))
    finally:
        sperre.release()
    assert r.status_code == 409
    assert "erstellt" in r.json()["detail"]


def test_erzeugen_blockiert_von_aussen_dann_frei(client, projekt_mit_inhalt, slug, monkeypatch):
    """Nach der Freigabe der Sperre ist die nächste Erstellung wieder möglich (kein 409)."""
    sperre = fs._sperre(projekt_mit_inhalt)
    sperre.acquire()
    sperre.release()
    monkeypatch.setattr(fs, "erzeugen", lambda p, e=None: {"ok": True, "formeln": 1, "seiten": 1,
                                                           "warnungen": [], "zeit": "x"})
    assert client.post(_url(slug, "formelsammlung")).status_code == 200


@pytest.mark.parametrize("node", ["/bin/false", "/gibt/es/nicht/node"])
def test_node_faellt_aus_500_ohne_pdf(client, projekt_mit_inhalt, slug, monkeypatch, node):
    monkeypatch.setenv("GENUT_NODE", node)
    r = client.post(_url(slug, "formelsammlung"))
    assert r.status_code == 500
    assert r.json()["detail"].startswith("PDF konnte nicht erstellt werden")
    assert not fs.pdf_pfad(projekt_mit_inhalt).exists()
    assert not list((projekt_mit_inhalt.ordner / "out").glob("formelsammlung*"))
    assert client.get(_url(slug, "formelsammlung.pdf")).status_code == 404
    assert client.get(_url(slug, "formeln")).json()["pdf"] is None


# ------------------------------------------------------------------ Mit Node und PDF

def _text(seite):
    return re.sub(r"\s+", " ", seite.get_textpage().get_text_range())


def test_erzeugen_pdf_eigenschaften(client, projekt_mit_inhalt, slug):
    _braucht_pdfkit()
    pdfium = pytest.importorskip("pypdfium2")

    r = client.post(_url(slug, "formelsammlung"), json={"eintraege": [_eintrag(F1)]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True and d["formeln"] == 1 and d["seiten"] >= 1
    assert d["warnungen"] == [] and d["zeit"]

    info = client.get(_url(slug, "formeln")).json()["pdf"]
    assert info["vorhanden"] is True and info["formeln"] == 1 and info["seiten"] == d["seiten"]

    r = client.get(_url(slug, "formelsammlung.pdf"))
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert f'filename="formelsammlung-{slug}.pdf"' in r.headers["content-disposition"]
    assert r.content.startswith(b"%PDF")

    pdf = pdfium.PdfDocument(r.content)
    try:
        assert len(pdf) == d["seiten"]
        text = ""
        for i in range(len(pdf)):
            seite = pdf[i]
            b, h = seite.get_size()
            assert abs(b - 595) <= 1 and abs(h - 842) <= 1
            text += " " + _text(seite)
        assert text.count(TITEL1) == 1
        assert TITEL2 not in text

        bild = pdf[0].render(scale=1).to_pil().convert("RGB")
        for _n, (rot, gruen, blau) in bild.getcolors(maxcolors=bild.width * bild.height):
            assert abs(rot - gruen) <= 2 and abs(gruen - blau) <= 2
    finally:
        pdf.close()


def test_erzeugen_mit_anderer_auswahl_tauscht_titel(client, slug):
    _braucht_pdfkit()
    pdfium = pytest.importorskip("pypdfium2")
    r = client.post(_url(slug, "formelsammlung"), json={"eintraege": [_eintrag(F2)]})
    assert r.status_code == 200, r.text
    pdf = pdfium.PdfDocument(client.get(_url(slug, "formelsammlung.pdf")).content)
    try:
        text = " ".join(_text(pdf[i]) for i in range(len(pdf)))
    finally:
        pdf.close()
    assert TITEL1 not in text
    assert TITEL2 in text


def test_erzeugen_ohne_body_nutzt_gespeicherte_auswahl(client, slug):
    _braucht_pdfkit()
    client.put(_url(slug, "formelauswahl"), json={"eintraege": [_eintrag(F1), _eintrag(F2)]})
    r = client.post(_url(slug, "formelsammlung"))
    assert r.status_code == 200, r.text
    assert r.json()["formeln"] == 2


# ------------------------------------------------------------------ Zusätze: Variablen, Erklärung, Kennzeichen (US2)

def _pdf_text(client, slug):
    pdfium = pytest.importorskip("pypdfium2")
    pdf = pdfium.PdfDocument(client.get(_url(slug, "formelsammlung.pdf")).content)
    try:
        return " ".join(_text(pdf[i]) for i in range(len(pdf)))
    finally:
        pdf.close()


def _erzeugen(client, slug, variablen=False, erklaerung=False, bloecke=(F2,)):
    eintraege = [{"block_id": b, "variablen": variablen, "erklaerung": erklaerung} for b in bloecke]
    r = client.post(_url(slug, "formelsammlung"), json={"eintraege": eintraege})
    assert r.status_code == 200, r.text
    return r.json()


def _formel_aendern(projekt, block_id, **felder):
    doc = projekt.inhalt()
    for t in doc.themen:
        for b in t.bloecke:
            if b.id == block_id:
                for k, v in felder.items():
                    setattr(b, k, v)
    projekt.inhalt_speichern(doc)


def test_variablen_schalter(client, projekt_mit_inhalt, slug):
    _braucht_pdfkit()
    from genut.schema import Variable

    _formel_aendern(projekt_mit_inhalt, F2, variablen=[Variable(name="s", bedeutung="zurückgelegter Weg")])
    _erzeugen(client, slug, variablen=True)
    assert "zurückgelegter Weg" in _pdf_text(client, slug)
    _erzeugen(client, slug, variablen=False)
    assert "zurückgelegter Weg" not in _pdf_text(client, slug)


def test_erklaertext_schalter(client, projekt_mit_inhalt, slug):
    _braucht_pdfkit()
    _formel_aendern(projekt_mit_inhalt, F2, erklaerung_md="Die **Länge** der Kurve zwischen Grenzen.")
    _erzeugen(client, slug, erklaerung=True)
    assert "Länge der Kurve zwischen Grenzen" in _pdf_text(client, slug)
    _erzeugen(client, slug, erklaerung=False)
    assert "Kurve zwischen Grenzen" not in _pdf_text(client, slug)


@pytest.mark.parametrize("status,wort", [("fehler", "nicht bestätigt"), ("nicht_pruefbar", "ungeprüft"),
                                         ("ok", None), ("ungeprueft", None)])
def test_kennzeichen_je_pruefergebnis(client, projekt_mit_inhalt, slug, status, wort):
    _braucht_pdfkit()
    from genut.schema import Pruefung

    _formel_aendern(projekt_mit_inhalt, F2, pruefung=Pruefung(status=status))
    _erzeugen(client, slug)
    text = _pdf_text(client, slug)
    assert TITEL2 in text
    for w in ("nicht bestätigt", "ungeprüft"):
        assert (w in text) is (w == wort)


def test_schalter_ohne_variablen_und_erklaerung_wirkungslos(client, slug):
    _braucht_pdfkit()
    # F2 hat weder Variablen noch Erklärung
    _erzeugen(client, slug, variablen=False, erklaerung=False)
    ohne = _pdf_text(client, slug)
    d = _erzeugen(client, slug, variablen=True, erklaerung=True)
    assert d["warnungen"] == []
    assert _pdf_text(client, slug) == ohne


def test_kaputtes_tex_warnung_pdf_trotzdem(client, projekt_mit_inhalt, slug):
    _braucht_pdfkit()
    _formel_aendern(projekt_mit_inhalt, F2, tex="\\frac{1}{")
    d = _erzeugen(client, slug, bloecke=(F1, F2))
    assert d["warnungen"] and d["formeln"] == 1
    assert any(TITEL2 in w for w in d["warnungen"])  # die Formel wird mit Namen gemeldet
    text = _pdf_text(client, slug)
    assert TITEL1 in text
    assert client.get(_url(slug, "formelsammlung.pdf")).status_code == 200


def test_alle_formeln_kaputt_500_ohne_pdf(client, projekt_mit_inhalt, slug):
    _braucht_pdfkit()
    _formel_aendern(projekt_mit_inhalt, F2, tex="\\frac{1}{")
    r = client.post(_url(slug, "formelsammlung"), json={"eintraege": [_eintrag(F2)]})
    assert r.status_code == 500
    assert r.json()["detail"].startswith("PDF konnte nicht erstellt werden")
    assert not fs.pdf_pfad(projekt_mit_inhalt).exists()
    assert client.get(_url(slug, "formelsammlung.pdf")).status_code == 404


# ------------------------------------------------------------------ Auswahl bleibt erhalten (US3)

def _neuer_client():
    from fastapi.testclient import TestClient

    from genut.server import app

    return TestClient(app)


def _formel_entfernen(projekt, block_id):
    doc = projekt.inhalt()
    for t in doc.themen:
        t.bloecke = [b for b in t.bloecke if b.id != block_id]
    projekt.inhalt_speichern(doc)


def test_auswahl_uebersteht_neustart(client, slug):
    eintraege = [{"block_id": F2, "variablen": False, "erklaerung": True}]
    assert client.put(_url(slug, "formelauswahl"), json={"eintraege": eintraege}).status_code == 200
    neu = _neuer_client()  # „Neustart“: frischer Client, Zustand nur von der Platte
    assert neu.get(_url(slug, "formeln")).json()["auswahl"] == [
        {"block_id": F2, "variablen": False, "erklaerung": True}]


def test_geloeschte_formel_verschwindet_aus_liste_und_auswahl(client, projekt_mit_inhalt, slug):
    client.put(_url(slug, "formelauswahl"), json={"eintraege": [_eintrag(F1), _eintrag(F2)]})
    _formel_entfernen(projekt_mit_inhalt, F2)
    d = client.get(_url(slug, "formeln")).json()
    assert [f["id"] for t in d["themen"] for f in t["formeln"]] == [F1]
    assert [e["block_id"] for e in d["auswahl"]] == [F1]


def test_geloeschte_formel_bricht_erstellung_nicht(client, projekt_mit_inhalt, slug):
    _braucht_pdfkit()
    client.put(_url(slug, "formelauswahl"), json={"eintraege": [_eintrag(F1), _eintrag(F2)]})
    _formel_entfernen(projekt_mit_inhalt, F2)
    r = client.post(_url(slug, "formelsammlung"))
    assert r.status_code == 200, r.text
    assert r.json()["formeln"] == 1


def test_neue_formel_ist_ungewaehlt(client, projekt_mit_inhalt, slug):
    client.put(_url(slug, "formelauswahl"), json={"eintraege": [_eintrag(F1)]})
    doc = projekt_mit_inhalt.inhalt()
    thema = doc.themen[-1]
    neu = next(b for b in thema.bloecke if b.id == F2).model_copy(update={"id": "b-00000099", "spick": True})
    thema.bloecke.append(neu)
    projekt_mit_inhalt.inhalt_speichern(doc)
    d = client.get(_url(slug, "formeln")).json()
    assert "b-00000099" in [f["id"] for t in d["themen"] for f in t["formeln"]]
    assert [e["block_id"] for e in d["auswahl"]] == [F1]
    assert [f["id"] for f, _e in fs.aufloesen(projekt_mit_inhalt)] == [F1]


def test_letzte_erzeugung_und_pdf_erneut_ladbar(client, projekt_mit_inhalt, slug):
    _braucht_pdfkit()
    d = client.post(_url(slug, "formelsammlung"), json={"eintraege": [_eintrag(F1)]}).json()
    pdf = client.get(_url(slug, "formeln")).json()["pdf"]
    assert pdf == {"vorhanden": True, "zeit": d["zeit"], "formeln": 1, "seiten": d["seiten"], "warnungen": []}
    # „Neustart“: Angaben und PDF sind weiterhin da, ohne neue Erzeugung
    neu = _neuer_client()
    assert neu.get(_url(slug, "formeln")).json()["pdf"] == pdf
    erst = neu.get(_url(slug, "formelsammlung.pdf"))
    zweit = neu.get(_url(slug, "formelsammlung.pdf"))
    assert erst.status_code == zweit.status_code == 200
    assert erst.content.startswith(b"%PDF") and erst.content == zweit.content
    # Auswahl speichern ändert die Angaben der letzten Erzeugung nicht
    client.put(_url(slug, "formelauswahl"), json={"eintraege": [_eintrag(F2)]})
    assert client.get(_url(slug, "formeln")).json()["pdf"] == pdf


def test_abgebrochener_lauf_laesst_vorhandenes_pdf_unberuehrt(client, projekt_mit_inhalt, slug, monkeypatch):
    ziel = fs.pdf_pfad(projekt_mit_inhalt)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    alt = b"%PDF-1.4 alte Fassung"
    ziel.write_bytes(alt)
    monkeypatch.setenv("GENUT_NODE", "/bin/false")
    r = client.post(_url(slug, "formelsammlung"), json={"eintraege": [_eintrag(F1)]})
    assert r.status_code == 500
    assert ziel.read_bytes() == alt
    assert [p.name for p in ziel.parent.iterdir()] == ["formelsammlung.pdf"]  # keine .tmp-Reste


# ------------------------------------------------------------------ Sonderfälle und Last (T017)

def _vervielfachen(projekt, anzahl, mit_zusaetzen=True):
    """Dokument-Umbau: die Formel F2 wird mit neuen Kennungen auf `anzahl` Formeln vervielfacht."""
    from genut.schema import Variable

    doc = projekt.inhalt()
    thema = doc.themen[-1]
    vorlage = next(b for b in thema.bloecke if b.id == F2)
    thema.bloecke = [b for b in thema.bloecke if b.typ != "formel"]
    ids = []
    for i in range(anzahl):
        feld = {"id": f"b-{9000 + i:08d}", "titel": f"Formel Nummer {i}", "spick": True}
        if mit_zusaetzen:
            feld["variablen"] = [Variable(name="s", bedeutung=f"Weg {i}"), Variable(name="t", bedeutung="Zeit")]
            feld["erklaerung_md"] = f"Erklärung {i}: Die **Länge** der Kurve, siehe \\(x^2\\)."
        thema.bloecke.append(vorlage.model_copy(update=feld))
        ids.append(feld["id"])
    projekt.inhalt_speichern(doc)
    return ids


def _seiten(client, slug):
    pdfium = pytest.importorskip("pypdfium2")
    pdf = pdfium.PdfDocument(client.get(_url(slug, "formelsammlung.pdf")).content)
    try:
        return len(pdf)
    finally:
        pdf.close()


def test_sonderzeichen_in_titel_variablen_erklaerung(client, projekt_mit_inhalt, slug):
    _braucht_pdfkit()
    from genut.schema import Variable

    _formel_aendern(
        projekt_mit_inhalt, F2, titel="Größe äöüß ≈ 5°",
        variablen=[Variable(name="\\alpha", bedeutung="Winkel α in ° für Öl, Übung und ß")],
        erklaerung_md="Näherung ≈ für kleine α bei 90° – Maß, Fläche, Ärger, Öffnung, Übergang.")
    d = _erzeugen(client, slug, variablen=True, erklaerung=True)
    assert d["warnungen"] == []
    text = _pdf_text(client, slug)
    assert "Größe äöüß ≈ 5°" in text
    assert "Winkel α in ° für Öl, Übung und ß" in text
    assert "Näherung ≈ für kleine α bei 90° – Maß, Fläche, Ärger, Öffnung, Übergang." in text


def test_sehr_lange_formel_wird_gesetzt(client, projekt_mit_inhalt, slug):
    _braucht_pdfkit()
    glieder = " + ".join(f"\\frac{{a_{{{i}}}}}{{b_{{{i}}}+1}}x^{{{i}}}" for i in range(1, 80))
    _formel_aendern(projekt_mit_inhalt, F2, tex=f"f(x) = {glieder}")
    d = _erzeugen(client, slug)
    assert d["ok"] is True and d["formeln"] == 1
    assert 1 <= d["seiten"] <= 2  # auf Seitenbreite skaliert, nicht auf viele Seiten verteilt
    assert _seiten(client, slug) == d["seiten"]
    assert TITEL2 in _pdf_text(client, slug)


def test_60_formeln_unter_15_sekunden(client, projekt_mit_inhalt, slug):
    import time

    _braucht_pdfkit()
    ids = _vervielfachen(projekt_mit_inhalt, 60)
    t0 = time.monotonic()
    d = _erzeugen(client, slug, variablen=True, erklaerung=True, bloecke=ids)
    dauer = time.monotonic() - t0
    assert dauer < 15, f"{dauer:.1f} s"
    assert d["formeln"] == 60 and d["warnungen"] == []
    assert 2 <= d["seiten"] <= 60
    assert _seiten(client, slug) == d["seiten"]
    text = _pdf_text(client, slug)
    assert "Formel Nummer 0" in text and "Formel Nummer 59" in text and "Weg 59" in text


def test_150_formeln_unter_30_sekunden(client, projekt_mit_inhalt, slug):
    import time

    _braucht_pdfkit()
    ids = _vervielfachen(projekt_mit_inhalt, 150)
    t0 = time.monotonic()
    d = _erzeugen(client, slug, variablen=True, erklaerung=True, bloecke=ids)
    dauer = time.monotonic() - t0
    assert dauer < 30, f"{dauer:.1f} s"
    assert d["formeln"] == 150 and d["warnungen"] == []
    assert _seiten(client, slug) == d["seiten"]


def test_erstellung_im_hintergrund_server_bleibt_erreichbar(client, projekt_mit_inhalt, slug):
    import threading
    import time

    _braucht_pdfkit()
    ids = _vervielfachen(projekt_mit_inhalt, 150)
    eintraege = [{"block_id": b, "variablen": True, "erklaerung": True} for b in ids]
    ergebnis = {}

    def lauf():
        ergebnis["r"] = _neuer_client().post(_url(slug, "formelsammlung"), json={"eintraege": eintraege})

    t = threading.Thread(target=lauf)
    t.start()
    try:
        sperre = fs._sperre(projekt_mit_inhalt)
        ende = time.monotonic() + 10
        while not sperre.locked() and time.monotonic() < ende and t.is_alive():
            time.sleep(0.01)
        assert sperre.locked(), "Erstellung hat nicht begonnen"

        t0 = time.monotonic()
        r = _neuer_client().get(_url(slug, "formeln"))
        assert r.status_code == 200
        assert time.monotonic() - t0 < 2  # Server blockiert nicht, solange node läuft
        assert t.is_alive()  # Erstellung lief während der Anfrage noch

        t0 = time.monotonic()
        r = _neuer_client().post(_url(slug, "formelsammlung"))
        assert r.status_code == 409
        assert time.monotonic() - t0 < 2
    finally:
        t.join(timeout=60)
    assert not t.is_alive()
    assert ergebnis["r"].status_code == 200, ergebnis["r"].text
    assert ergebnis["r"].json()["formeln"] == 150
