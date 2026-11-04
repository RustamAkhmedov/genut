"""Strukturformeln: Raster-Layout der Valenzstrichformel und SVG-Ausgabe."""
import re
from types import SimpleNamespace as N

import pytest

pytest.importorskip("rdkit")

from rdkit import Chem  # noqa: E402

from genut.render.struktur import _raster, skelett_svg, struktur, summenformel, valenzstrich_svg  # noqa: E402


def raster(smiles):
    mh = Chem.AddHs(Chem.MolFromSmiles(smiles))
    Chem.Kekulize(mh, clearAromaticFlags=True)
    return mh, _raster(mh)


@pytest.mark.parametrize("smiles", ["C", "CCO", "CCCC", "CC(C)C", "CC(C)(C)C", "CC(C)CC", "C=C", "C=CC", "C#C",
                                    "CC=O", "CC(C)=O", "CC(=O)O", "CC(=O)OCC", "CCN", "CCl", "OCC(O)CO", "O=C=O", "O"])
def test_kettenmolekuele_auf_dem_raster(smiles):
    mh, pos = raster(smiles)
    assert pos is not None and len(pos) == mh.GetNumAtoms()
    for b in mh.GetBonds():   # nur waagrechte/senkrechte Bindungen
        p, q = pos[b.GetBeginAtomIdx()], pos[b.GetEndAtomIdx()]
        assert p[0] == q[0] or p[1] == q[1]


def test_hauptkette_waagrecht():
    mh, pos = raster("C=CC")          # Propen: alle drei C auf einer Zeile
    assert len({pos[a.GetIdx()][1] for a in mh.GetAtoms() if a.GetSymbol() == "C"}) == 1
    mh, pos = raster("CC=O")          # Ethanal: =O steht über dem C, nicht in der Kette
    o = next(a for a in mh.GetAtoms() if a.GetSymbol() == "O")
    c = o.GetNeighbors()[0]
    assert pos[o.GetIdx()][0] == pos[c.GetIdx()][0] and pos[o.GetIdx()][1] < pos[c.GetIdx()][1]


@pytest.mark.parametrize("smiles", ["c1ccccc1", "C1CCCCC1", "C/C=C/C", "C/C=C\\C"])
def test_ringe_und_cis_trans_nicht_auf_dem_raster(smiles):
    assert raster(smiles)[1] is None


def test_svg_ohne_feste_farben():
    for s in (valenzstrich_svg("CCO"), valenzstrich_svg("C/C=C\\C"), skelett_svg("c1ccccc1")):
        assert s.startswith("<svg") and 'class="struktur-svg"' in s
        assert not re.search(r"#000000|#FFFFFF|fill:#fff", s, re.I), "Farben müssen über currentColor laufen (Dunkelmodus)"
    assert valenzstrich_svg("CCO").count(">H<") == 6


def test_struktur_fuer_vorlage():
    s = struktur(N(smiles="CCO", name="Ethanol", darstellung="beide"))
    assert [b["label"] for b in s["bilder"]] == ["Valenzstrichformel", "Skelettformel"] and s["fehler"] is None
    s = struktur(N(smiles="C#C", name="Ethin", darstellung="beide"))   # Skelett wäre nur ein Strich
    assert [b["label"] for b in s["bilder"]] == ["Valenzstrichformel"]
    s = struktur(N(smiles="C1CC", name="kaputt", darstellung="beide"))
    assert s["bilder"] == [] and "nicht lesbar" in s["fehler"]
    assert summenformel("CC(=O)[O-]") == "C2H3O2^-"
