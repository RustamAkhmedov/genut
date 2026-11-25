import shutil
from pathlib import Path

import pytest

from genut import formelsammlung as fs
from genut.formelsammlung import AuswahlEintrag, UnbekannteFormel
from genut.projekt import Projekt
from genut.schema import Dokument, FormelBlock

FIX = Path(__file__).parent / "fixtures"
F1, F2 = "b-00000003", "b-00000011"  # Formeln in tests/fixtures/integral
NICHT_FORMEL = "b-00000001"


@pytest.fixture
def projekt_sprachen(projekte):
    p = Projekt.anlegen("Test Sprachen")
    p.inhalt_speichern(Dokument.model_validate_json((FIX / "sprachen" / "inhalt.json").read_text(encoding="utf-8")))
    return p


def _ids(paare):
    return [f["id"] for f, _ in paare]


def _formel(id_, spick=False):
    return FormelBlock(typ="formel", id=id_, quelle="foto", foto="001.jpg", spick=spick, titel=id_, tex="x")


def test_formelliste_in_projektreihenfolge(projekt_mit_inhalt):
    liste = fs.formeln(projekt_mit_inhalt.inhalt())
    assert [f["id"] for f in liste] == [F1, F2]
    assert liste[0]["thema_id"] == "t-00000001"
    assert liste[0]["spick"] is True
    assert liste[0]["pruefung"] == "ungeprueft"


def test_standardauswahl_sind_spickzettel_formeln(projekt_mit_inhalt):
    doc = projekt_mit_inhalt.inhalt()
    doc.themen[1].bloecke[0].spick = False
    projekt_mit_inhalt.inhalt_speichern(doc)
    a = fs.auswahl_laden(projekt_mit_inhalt)
    assert [e.block_id for e in a.eintraege] == [F1]
    assert a.eintraege[0].variablen is True and a.eintraege[0].erklaerung is False
    assert a.letzte_erzeugung is None
    assert not (projekt_mit_inhalt.ordner / "formelsammlung.json").exists()


def test_keine_formeln_leere_liste(projekt_sprachen):
    assert fs.formeln(projekt_sprachen.inhalt()) == []
    assert fs.auswahl_laden(projekt_sprachen).eintraege == []
    assert fs.aufloesen(projekt_sprachen) == []


def test_auswahl_speichern_und_laden(projekt_mit_inhalt):
    fs.auswahl_speichern(projekt_mit_inhalt, [AuswahlEintrag(block_id=F2, variablen=False, erklaerung=True)])
    a = fs.auswahl_laden(projekt_mit_inhalt)
    assert [e.block_id for e in a.eintraege] == [F2]
    assert a.eintraege[0].variablen is False and a.eintraege[0].erklaerung is True
    assert (projekt_mit_inhalt.ordner / "formelsammlung.json").exists()


def test_leere_auswahl_ersetzt_standard(projekt_mit_inhalt):
    fs.auswahl_speichern(projekt_mit_inhalt, [])
    assert fs.auswahl_laden(projekt_mit_inhalt).eintraege == []
    assert fs.aufloesen(projekt_mit_inhalt) == []


@pytest.mark.parametrize("kennung", ["b-gibtsnicht", NICHT_FORMEL])
def test_unbekannte_oder_nicht_formel_kennung(projekt_mit_inhalt, kennung):
    with pytest.raises(UnbekannteFormel):
        fs.auswahl_speichern(projekt_mit_inhalt, [AuswahlEintrag(block_id=F1), AuswahlEintrag(block_id=kennung)])
    assert not (projekt_mit_inhalt.ordner / "formelsammlung.json").exists()


def test_doppelte_kennungen_der_letzte_gewinnt(projekt_mit_inhalt):
    a = fs.auswahl_speichern(projekt_mit_inhalt, [
        AuswahlEintrag(block_id=F1, erklaerung=False),
        AuswahlEintrag(block_id=F2),
        AuswahlEintrag(block_id=F1, erklaerung=True),
    ])
    assert sorted(e.block_id for e in a.eintraege) == [F1, F2]
    assert {e.block_id: e.erklaerung for e in fs.auswahl_laden(projekt_mit_inhalt).eintraege}[F1] is True


def test_geloeschte_formel_wird_ignoriert(projekt_mit_inhalt):
    fs.auswahl_speichern(projekt_mit_inhalt, [AuswahlEintrag(block_id=F1), AuswahlEintrag(block_id=F2)])
    doc = projekt_mit_inhalt.inhalt()
    doc.themen[0].bloecke = [b for b in doc.themen[0].bloecke if b.id != F1]
    projekt_mit_inhalt.inhalt_speichern(doc)
    assert _ids(fs.aufloesen(projekt_mit_inhalt)) == [F2]


def test_neue_formel_ist_ungewaehlt(projekt_mit_inhalt):
    fs.auswahl_speichern(projekt_mit_inhalt, [AuswahlEintrag(block_id=F1)])
    doc = projekt_mit_inhalt.inhalt()
    doc.themen[1].bloecke.append(_formel("b-neu", spick=True))
    projekt_mit_inhalt.inhalt_speichern(doc)
    assert "b-neu" in [f["id"] for f in fs.formeln(projekt_mit_inhalt.inhalt())]
    assert _ids(fs.aufloesen(projekt_mit_inhalt)) == [F1]


def test_reihenfolge_ist_themenreihenfolge(projekt_mit_inhalt):
    # Auswahl absichtlich in umgekehrter Reihenfolge speichern
    fs.auswahl_speichern(projekt_mit_inhalt, [AuswahlEintrag(block_id=F2), AuswahlEintrag(block_id=F1)])
    assert _ids(fs.aufloesen(projekt_mit_inhalt)) == [F1, F2]
    # Themen vertauschen: die Reihenfolge folgt dem Projekt
    doc = projekt_mit_inhalt.inhalt()
    doc.themen.reverse()
    projekt_mit_inhalt.inhalt_speichern(doc)
    assert _ids(fs.aufloesen(projekt_mit_inhalt)) == [F2, F1]


@pytest.mark.parametrize("inhalt", ["{kaputt", '{"eintraege": "nein"}', ""])
def test_kaputte_datei_ergibt_standard(projekt_mit_inhalt, inhalt):
    (projekt_mit_inhalt.ordner / "formelsammlung.json").write_text(inhalt, encoding="utf-8")
    assert [e.block_id for e in fs.auswahl_laden(projekt_mit_inhalt).eintraege] == [F1, F2]


def test_letzte_erzeugung_bleibt_beim_speichern(projekt_mit_inhalt):
    a = fs.auswahl_laden(projekt_mit_inhalt)
    a.letzte_erzeugung = fs.LetzteErzeugung(zeit="2026-11-15T10:12:00", formeln=2, seiten=1, warnungen=["w"])
    (projekt_mit_inhalt.ordner / "formelsammlung.json").write_text(a.model_dump_json(), encoding="utf-8")
    neu = fs.auswahl_speichern(projekt_mit_inhalt, [AuswahlEintrag(block_id=F1)])
    assert neu.letzte_erzeugung == a.letzte_erzeugung
    assert fs.auswahl_laden(projekt_mit_inhalt).letzte_erzeugung.warnungen == ["w"]


# ------------------------------------------------------------------ Markdown → Textstücke (US2)

def _st(t, s, **extra):
    return {"t": t, "s": s, **extra}


@pytest.mark.parametrize("md", [None, "", "   \n\n "])
def test_stuecke_leerer_text(md):
    assert fs.erklaerung_stuecke(md) == []


def test_stuecke_absaetze():
    assert fs.erklaerung_stuecke("Erster Absatz.\n\nZweiter Absatz.") == [
        [_st("text", "Erster Absatz.")], [_st("text", "Zweiter Absatz.")]]


def test_stuecke_fett_kursiv_code():
    assert fs.erklaerung_stuecke("a **fett** b *kursiv* c `code` d") == [[
        _st("text", "a "), _st("fett", "fett"), _st("text", " b "), _st("kursiv", "kursiv"),
        _st("text", " c "), _st("code", "code"), _st("text", " d")]]


@pytest.mark.parametrize("md", ["Es gilt \\(x^2\\) hier", "Es gilt $x^2$ hier"])
def test_stuecke_formel_im_text(md):
    assert fs.erklaerung_stuecke(md) == [[_st("text", "Es gilt "), _st("formel", "x^2"), _st("text", " hier")]]


def test_stuecke_dollar_mit_leerraum_bleibt_text():
    (absatz,) = fs.erklaerung_stuecke("5 $ und 6 $ zusammen")
    assert [s["t"] for s in absatz] == ["text"]
    assert absatz[0]["s"] == "5 $ und 6 $ zusammen"


def test_stuecke_aufzaehlung_punkt_am_ersten_stueck():
    assert fs.erklaerung_stuecke("- eins **zwei**\n- drei \\(x\\)") == [
        [_st("text", "eins ", punkt=True), _st("fett", "zwei")],
        [_st("text", "drei ", punkt=True), _st("formel", "x")]]


@pytest.mark.parametrize("md", ["Davor\n\n\\[a^2+b^2=c^2\\]\n\nDanach", "Davor\n\n$$a^2+b^2=c^2$$\n\nDanach"])
def test_stuecke_abgesetzte_formel(md):
    absaetze = fs.erklaerung_stuecke(md)
    assert absaetze[0] == [_st("text", "Davor")]
    assert absaetze[-1] == [_st("text", "Danach")]
    bloecke = [s for a in absaetze for s in a if s["t"] == "formel_block"]
    assert bloecke == [_st("formel_block", "a^2+b^2=c^2")]


def test_stuecke_unbekanntes_markdown_wird_einfacher_text():
    md = "# Überschrift\n\n[Link](http://x.de) und <b>html</b>\n\n| a | b |\n|---|---|\n| 1 | 2 |"
    absaetze = fs.erklaerung_stuecke(md)
    assert absaetze
    for a in absaetze:
        assert {s["t"] for s in a} == {"text"}
    text = " ".join(s["s"] for a in absaetze for s in a)
    for wort in ("Überschrift", "Link", "html", "1", "2"):
        assert wort in text
    assert "#" not in text and "](" not in text
