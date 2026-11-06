import time

import pytest

from genut.pruefer import elemente, pruefe
from genut.pruefer.sandbox import ARBEITER, Unsicher, Zeitueberschreitung, bezeichner_pruefen
from genut.schema import CheckGleich


@pytest.mark.parametrize("ausdruck,erwartet,ok", [
    ("integrate(x**2, (x, 0, 2))", "8/3", True),
    ("integrate(x**2, (x, 0, 2))", "4/3", False),
    ("diff(x*sin(x), x)", "x*cos(x) + sin(x)", True),
    ("integrate(sqrt(1+x), (x, 0, 3))", "14/3", True),
    ("limit(sin(x)/x, x, 0)", "1", True),
    ("integrate(exp(-x**2), (x, -oo, oo))", "sqrt(pi)", True),
])
def test_gleich(ausdruck, erwartet, ok):
    assert ARBEITER.ausfuehren("check_gleich", ausdruck, erwartet)[0] is ok


def test_numerisch():
    assert ARBEITER.ausfuehren("check_numerisch", "integrate(sqrt(1+x),(x,0,3))", 4.667, 0.01)[0]
    ok, m = ARBEITER.ausfuehren("check_numerisch", "integrate(sqrt(1+x),(x,0,3))", 4.5, 0.01)
    assert not ok and "4.66" in m


def test_loesungen():
    assert ARBEITER.ausfuehren("check_loesungen", ["x**2 - 4"], ["x"], [{"x": "-2"}, {"x": "2"}])[0]
    assert not ARBEITER.ausfuehren("check_loesungen", ["x**2 - 4"], ["x"], [{"x": "2"}])[0]
    assert not ARBEITER.ausfuehren("check_loesungen", ["x**2 - 4"], ["x"], [{"x": "3"}, {"x": "-2"}])[0]
    assert ARBEITER.ausfuehren("check_loesungen", ["Eq(x + y, 3)", "x - y - 1"], ["x", "y"], [{"x": "2", "y": "1"}])[0]


@pytest.mark.parametrize("boese", [
    "__import__('os')", "x.__class__", "os.system(1)", "lambda: 1", "eval(1)", "open(x)",
    "getattr(x, y)", "x; y", "Symbol", "exec", "a.b",
])
def test_sandbox_lehnt_ab(boese):
    with pytest.raises(Unsicher):
        bezeichner_pruefen(boese, {"sin", "integrate"})


def test_zeitueberschreitung():
    t = time.time()
    with pytest.raises(Zeitueberschreitung):
        ARBEITER.ausfuehren("check_gleich", "factorial(10**9)", "1", timeout=3)
    assert time.time() - t < 30
    assert ARBEITER.ausfuehren("check_gleich", "1+1", "2")[0]  # Arbeiter wurde ersetzt


def test_graph():
    g = {"x_min": -3, "x_max": 3, "funktionen": [{"ausdruck": "a*x**2+1"}],
         "parameter": [{"name": "a", "min": -3, "max": 3, "schritt": 0.1, "start": 1}]}
    f, js = ARBEITER.ausfuehren("graph_pruefen", g)
    assert f == [] and js == ["a*Math.pow(x, 2) + 1"]
    f, js = ARBEITER.ausfuehren("graph_pruefen", {"x_min": -3, "x_max": 3, "funktionen": [{"ausdruck": "log(x)"}]})
    assert f and js == [None]
    f, _ = ARBEITER.ausfuehren("graph_pruefen", {"x_min": 0, "x_max": 1, "funktionen": [{"ausdruck": "x"}],
                                                 "parameter": [{"name": "x", "min": 0, "max": 1, "schritt": 1, "start": 0}]})
    assert any("unzulässig" in m for m in f)


def test_graph_parameter_ohne_wirkung():
    """Ein Regler, dessen Parameter in keiner Funktion vorkommt, würde nichts bewegen."""
    g = {"x_min": -3, "x_max": 3, "funktionen": [{"ausdruck": "a*x**2"}, {"ausdruck": "x + 1"}],
         "parameter": [{"name": "a", "min": 0, "max": 3, "schritt": 0.1, "start": 1},
                       {"name": "k", "min": 0, "max": 3, "schritt": 0.1, "start": 1}]}
    f, _ = ARBEITER.ausfuehren("graph_pruefen", g)
    assert len(f) == 1 and "Parameter k" in f[0] and "keiner Funktion" in f[0]


def test_fixture_status(doc):
    from tests.conftest import FIX

    erg = pruefe(doc, set(elemente(doc)), FIX / "fotos")
    assert erg["a-00000001"].status == "ok"      # gleich
    assert erg["a-00000002"].status == "ok"      # loesungen
    assert erg["a-00000003"].status == "ok"      # numerisch
    assert erg["a-00000004"].status == "fehler"  # falsches Ergebnis
    assert erg["a-00000005"].status == "nicht_pruefbar"
    assert erg["b-00000003"].status == "ok"      # Graph mit Parameter
    assert erg["b-00000014"].status == "fehler"  # log(x) auf [-3, 3]
    assert erg["k-00000008"].status == "fehler"  # kaputtes TeX
    assert erg["b-00000001"].status == "ungeprueft"
    assert doc.aufgaben[0].gesperrt is True
    assert doc.themen[0].bloecke[2].graph.funktionen[0].ausdruck_js


def test_dollar_und_bbox(doc):
    from tests.conftest import FIX

    doc.themen[0].bloecke[0].md = "Mit $x^2$ geschrieben"
    doc.themen[0].bloecke[4].bbox = [0.5, 0.5, 0.8, 0.1]
    erg = pruefe(doc, {"b-00000001", "b-00000005"}, FIX / "fotos")
    assert erg["b-00000001"].status == "fehler"
    assert erg["b-00000005"].status == "fehler"


def test_check_modell():
    c = CheckGleich(art="gleich", ausdruck="1", erwartet="1")
    assert c.art == "gleich"


def test_abgestuerzter_arbeiter_bricht_nichts_ab(monkeypatch):
    """Stirbt der Arbeiterprozess mitten im Auftrag, gibt es Absturz (= nicht prüfbar) statt ConnectionResetError."""
    import multiprocessing as mp
    import os

    from genut.pruefer.sandbox import Absturz, Arbeiter
    a = Arbeiter()

    def sterbender_start():
        ktx = mp.get_context("spawn")
        a._ltg, kind = ktx.Pipe()
        a._proz = ktx.Process(target=os._exit, args=(3,), daemon=True)   # antwortet nie, Verbindung reißt ab
        a._proz.start()
        kind.close()

    monkeypatch.setattr(a, "_starten", sterbender_start)
    with pytest.raises(Absturz):
        a.ausfuehren("check_gleich", "1", "1", timeout=5)
    assert issubclass(Absturz, Zeitueberschreitung)
    from genut.pruefer import _check
    from genut.pruefer import sandbox
    monkeypatch.setattr(sandbox, "ARBEITER", a)
    import genut.pruefer as pr
    monkeypatch.setattr(pr, "ARBEITER", a)
    assert _check(CheckGleich(art="gleich", ausdruck="1", erwartet="1"))[0] is None   # nicht prüfbar, kein Absturz
