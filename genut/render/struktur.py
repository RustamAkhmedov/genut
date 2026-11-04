"""Strukturformeln (Chemie): SMILES → SVG beim Bauen der Seite, offline und in hell/dunkel (currentColor).

- Skelettformel: Zeichnung von RDKit (Zickzack, C und H weggelassen, Heteroatome beschriftet).
- Valenzstrichformel: wie im Schulbuch auf einem rechtwinkligen Raster – Hauptkette waagrecht, H-Atome und
  Seitenketten oben/unten. Ringe, cis/trans und alles, was auf dem Raster kollidieren würde, zeichnet RDKit
  mit allen H-Atomen.
Ohne RDKit oder bei unlesbarem SMILES liefert `struktur()` keine Bilder, aber eine Fehlermeldung.
"""
from __future__ import annotations

import html
from collections import Counter
from functools import lru_cache

from markupsafe import Markup

EINHEIT = 38            # px pro Bindung im Raster
SCHRIFT = 17            # px
LABEL_RADIUS = 0.3      # Bindungen enden so weit (in Bindungslängen) vor einer Beschriftung
SKELETT_PX = 44         # px pro Bindung in der Skelettformel


class StrukturFehler(ValueError):
    pass


def _mol(smiles: str):
    from rdkit import Chem, RDLogger
    RDLogger.DisableLog("rdApp.*")
    m = Chem.MolFromSmiles((smiles or "").strip())
    if m is None or m.GetNumAtoms() == 0:
        raise StrukturFehler(f"SMILES {smiles!r} ist nicht lesbar")
    return m


def atome(smiles: str) -> Counter:
    """Atome inkl. impliziter H, z. B. CCO → C2 H6 O1."""
    from rdkit import Chem
    m = Chem.AddHs(_mol(smiles))
    return Counter(a.GetSymbol() for a in m.GetAtoms())


def summenformel(smiles: str) -> str:
    """Hill-Schreibweise in mhchem-Syntax, z. B. C2H6O."""
    from rdkit.Chem.rdMolDescriptors import CalcMolFormula
    return CalcMolFormula(_mol(smiles)).replace("+", "^+").replace("-", "^-")


# ---------------------------------------------------------------- Valenzstrichformel auf dem Raster

_RICHTUNG = {"r": (1, 0), "l": (-1, 0), "o": (0, -1), "u": (0, 1)}
_SENKRECHT = {"r": "ou", "l": "ou", "o": "lr", "u": "lr"}


def _hauptkette(mh, schwer: list[int]) -> list[int]:
    """Längster Pfad zwischen Nicht-H-Atomen; endständige =O (Aldehyd, Keton) lieber nach oben als in die Kette."""
    if len(schwer) == 1:
        return schwer
    nachbarn = {i: [n.GetIdx() for n in mh.GetAtomWithIdx(i).GetNeighbors() if n.GetAtomicNum() != 1]
                for i in schwer}

    def pfade_ab(start):
        stapel, out = [[start]], []
        while stapel:
            p = stapel.pop()
            out.append(p)
            stapel += [p + [n] for n in nachbarn[p[-1]] if n not in p]
        return out

    def strafe(p):
        s = 0.0
        for ende, inneres in ((p[0], p[1:2]), (p[-1], p[-2:-1])):
            if not inneres:
                continue
            b = mh.GetBondBetweenAtoms(ende, inneres[0])
            partner = mh.GetAtomWithIdx(inneres[0])
            heteroatom = mh.GetAtomWithIdx(ende).GetSymbol() != "C"
            if heteroatom and b.GetBondTypeAsDouble() == 2 and len(nachbarn[ende]) == 1 and partner.GetDegree() >= 3:
                s += 1.5
        return s

    def wert(p):
        return (len(p) - strafe(p), sum(mh.GetAtomWithIdx(i).GetSymbol() == "C" for i in p), -p[0])

    kandidaten = [p for s in schwer for p in pfade_ab(s)]
    return max(kandidaten, key=wert)


def _raster(mh) -> dict[int, tuple[int, int]] | None:
    from rdkit import Chem
    if mh.GetRingInfo().NumRings():
        return None
    if any(b.GetStereo() != Chem.BondStereo.STEREONONE for b in mh.GetBonds()):
        return None
    if any(a.GetDegree() > 4 for a in mh.GetAtoms()):
        return None
    schwer = [a.GetIdx() for a in mh.GetAtoms() if a.GetAtomicNum() != 1]
    if not schwer:  # H2
        return {0: (0, 0), 1: (1, 0)} if mh.GetNumAtoms() == 2 else None
    kette = _hauptkette(mh, schwer)
    pos: dict[int, tuple[int, int]] = {a: (i, 0) for i, a in enumerate(kette)}

    def anhaengen(atom: int, frei: str, herkunft: str | None):
        """Nachbarn von atom, die noch keine Position haben, auf die freien Richtungen verteilen."""
        x, y = pos[atom]
        rest = [n for n in mh.GetAtomWithIdx(atom).GetNeighbors() if n.GetIdx() not in pos]
        # schwere Nachbarn zuerst (Doppelbindung nach oben), dann H
        rest.sort(key=lambda n: (n.GetAtomicNum() == 1,
                                 -mh.GetBondBetweenAtoms(atom, n.GetIdx()).GetBondTypeAsDouble()))
        frei = list(frei)
        for n in rest:
            if not frei:
                raise StrukturFehler("kein Platz")
            if n.GetAtomicNum() == 1:
                wahl = next(r for r in "lrou" if r in frei)
                if herkunft and herkunft in frei:   # in einer Seitenkette: H zuerst geradeaus weiter
                    wahl = herkunft
                frei.remove(wahl)
                dx, dy = _RICHTUNG[wahl]
                pos[n.GetIdx()] = (x + dx, y + dy)
            else:
                wahl = next(r for r in ("o", "u", "r", "l") if r in frei) if herkunft is None else (
                    herkunft if herkunft in frei else frei[0])
                frei.remove(wahl)
                dx, dy = _RICHTUNG[wahl]
                weite = 1 if herkunft == wahl else 2   # Abzweigungen doppelt so lang: Platz für die H daneben
                pos[n.GetIdx()] = (x + dx * weite, y + dy * weite)
                anhaengen(n.GetIdx(), wahl + _SENKRECHT[wahl], wahl)

    for i, a in enumerate(kette):
        frei = "ou" + ("l" if i == 0 else "") + ("r" if i == len(kette) - 1 else "")
        anhaengen(a, frei, None)
    return pos if _kollisionsfrei(mh, pos) else None


def _kollisionsfrei(mh, pos) -> bool:
    if len(set(pos.values())) != len(pos):
        return False
    belegt = set(pos.values())
    strecken = []
    for b in mh.GetBonds():
        p, q = pos[b.GetBeginAtomIdx()], pos[b.GetEndAtomIdx()]
        if p[0] != q[0] and p[1] != q[1]:
            return False
        # Zwischenpunkte einer langen Bindung müssen frei sein
        n = max(abs(p[0] - q[0]), abs(p[1] - q[1]))
        for k in range(1, n):
            if (p[0] + (q[0] - p[0]) * k // n, p[1] + (q[1] - p[1]) * k // n) in belegt:
                return False
        strecken.append((p, q))
    for i, (a, b) in enumerate(strecken):
        for c, d in strecken[i + 1:]:
            if {a, b} & {c, d}:
                continue
            if _schneiden(a, b, c, d):
                return False
    return True


def _schneiden(a, b, c, d) -> bool:
    def box(p, q):
        return min(p[0], q[0]), max(p[0], q[0]), min(p[1], q[1]), max(p[1], q[1])
    x1, x2, y1, y2 = box(a, b)
    x3, x4, y3, y4 = box(c, d)
    return x1 <= x4 and x3 <= x2 and y1 <= y4 and y3 <= y2


def _label(atom) -> str:
    q = atom.GetFormalCharge()
    t = html.escape(atom.GetSymbol())
    if q:
        z = ("" if abs(q) == 1 else str(abs(q))) + ("+" if q > 0 else "−")
        t += f'<tspan dy="-7" font-size="{SCHRIFT * 0.7:.0f}">{z}</tspan>'
    return t


def _raster_svg(mh, pos, titel: str) -> str:
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    rand = 0.55
    x0, y0 = min(xs) - rand, min(ys) - rand
    b, h = (max(xs) - min(xs) + 2 * rand) * EINHEIT, (max(ys) - min(ys) + 2 * rand) * EINHEIT
    P = lambda p: ((p[0] - x0) * EINHEIT, (p[1] - y0) * EINHEIT)  # noqa: E731
    teile = [f'<svg class="struktur-svg" viewBox="0 0 {b:.0f} {h:.0f}" width="{b:.0f}" height="{h:.0f}" role="img" '
             f'aria-label="{html.escape(titel)}" font-family="var(--sans)" font-size="{SCHRIFT}">']
    for bd in mh.GetBonds():
        (ax, ay), (bx, by) = P(pos[bd.GetBeginAtomIdx()]), P(pos[bd.GetEndAtomIdx()])
        laenge = max(abs(bx - ax), abs(by - ay))
        ux, uy = (bx - ax) / laenge, (by - ay) / laenge
        k = LABEL_RADIUS * EINHEIT
        ax, ay, bx, by = ax + ux * k, ay + uy * k, bx - ux * k, by - uy * k
        ordnung = {1.0: 1, 1.5: 2, 2.0: 2, 3.0: 3}.get(bd.GetBondTypeAsDouble(), 1)
        versatz = {1: [0], 2: [-3, 3], 3: [-4.5, 0, 4.5]}[ordnung]
        for v in versatz:
            nx, ny = -uy * v, ux * v
            teile.append(f'<line x1="{ax + nx:.1f}" y1="{ay + ny:.1f}" x2="{bx + nx:.1f}" y2="{by + ny:.1f}" '
                         f'stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>')
    for i, p in pos.items():
        x, y = P(p)
        teile.append(f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="middle" dominant-baseline="central" '
                     f'fill="currentColor">{_label(mh.GetAtomWithIdx(i))}</text>')
    teile.append("</svg>")
    return "".join(teile)


# ---------------------------------------------------------------- Zeichnungen von RDKit

def _rdkit_svg(m, titel: str, alle_c: bool) -> str:
    import re

    from rdkit.Chem import rdDepictor
    from rdkit.Chem.Draw import rdMolDraw2D
    rdDepictor.SetPreferCoordGen(True)
    rdDepictor.Compute2DCoords(m)
    konf = m.GetConformer()
    _doppelbindung_waagrecht(m, konf)
    xs = [konf.GetAtomPosition(i).x for i in range(m.GetNumAtoms())]
    ys = [konf.GetAtomPosition(i).y for i in range(m.GetNumAtoms())]
    # RDKit-Koordinaten: Bindungslänge ≈ 1,5 (CoordGen) bzw. 1 – auf die mittlere Bindungslänge normieren
    bl = [((konf.GetAtomPosition(b.GetBeginAtomIdx()) - konf.GetAtomPosition(b.GetEndAtomIdx())).Length())
          for b in m.GetBonds()] or [1.0]
    einheit = sum(bl) / len(bl)
    px = (EINHEIT if alle_c else SKELETT_PX) / einheit
    breite = int((max(xs) - min(xs)) * px + 2 * 0.7 * px * einheit)
    hoehe = int((max(ys) - min(ys)) * px + 2 * 0.7 * px * einheit)
    d = rdMolDraw2D.MolDraw2DSVG(max(breite, 40), max(hoehe, 40))
    o = d.drawOptions()
    o.useBWAtomPalette()
    o.clearBackground = False
    o.bondLineWidth = 1.6
    o.scaleBondWidth = False
    o.fixedBondLength = px * einheit
    o.fixedFontSize = SCHRIFT
    o.padding = 0.0
    o.multipleBondOffset = 0.18
    if alle_c:
        for a in m.GetAtoms():
            if a.GetSymbol() == "C":
                o.atomLabels[a.GetIdx()] = "C"
    d.DrawMolecule(m)
    d.FinishDrawing()
    s = d.GetDrawingText()
    s = s[s.index("<svg"):]
    s = re.sub(r"#000000|#000\b", "currentColor", s)
    s = re.sub(r"<svg[^>]*?width='(\d+)px'[^>]*?height='(\d+)px'[^>]*?>",
               lambda mm: f'<svg class="struktur-svg" viewBox="0 0 {mm.group(1)} {mm.group(2)}" width="{mm.group(1)}" '
                          f'height="{mm.group(2)}" role="img" aria-label="{html.escape(titel)}">', s, count=1)
    return re.sub(r"<!--.*?-->|<\?xml[^>]*\?>", "", s, flags=re.S)


def _doppelbindung_waagrecht(m, konf) -> None:
    """cis/trans wie im Schulbuch: die erste Doppelbindung mit Stereo-Angabe waagrecht legen."""
    import math

    from rdkit import Chem
    from rdkit.Geometry import Point3D
    b = next((b for b in m.GetBonds() if b.GetStereo() != Chem.BondStereo.STEREONONE), None)
    if b is None:
        return
    p, q = konf.GetAtomPosition(b.GetBeginAtomIdx()), konf.GetAtomPosition(b.GetEndAtomIdx())
    w = -math.atan2(q.y - p.y, q.x - p.x)
    c, s = math.cos(w), math.sin(w)
    for i in range(m.GetNumAtoms()):
        r = konf.GetAtomPosition(i)
        konf.SetAtomPosition(i, Point3D(r.x * c - r.y * s, r.x * s + r.y * c, 0))


@lru_cache(maxsize=512)
def valenzstrich_svg(smiles: str, titel: str = "Valenzstrichformel") -> str:
    from rdkit import Chem
    mh = Chem.AddHs(_mol(smiles))
    Chem.Kekulize(mh, clearAromaticFlags=True)
    pos = None
    try:
        pos = _raster(mh)
    except StrukturFehler:
        pos = None
    if pos is not None:
        return _raster_svg(mh, pos, titel)
    return _rdkit_svg(mh, titel, alle_c=True)


@lru_cache(maxsize=512)
def skelett_svg(smiles: str, titel: str = "Skelettformel") -> str:
    return _rdkit_svg(_mol(smiles), titel, alle_c=False)


def struktur(b) -> dict:
    """Für die Vorlage: Bilder (je nach darstellung), Summenformel aus dem SMILES oder Fehlermeldung."""
    try:
        m = _mol(b.smiles)
    except ImportError:
        return {"bilder": [], "fehler": "RDKit ist nicht installiert – Strukturformel kann nicht gezeichnet werden."}
    except StrukturFehler as e:
        return {"bilder": [], "fehler": str(e)}
    arten = {"valenzstrich": ["valenzstrich"], "skelett": ["skelett"],
             "beide": ["valenzstrich", "skelett"]}.get(b.darstellung, ["valenzstrich", "skelett"])
    schwer = sum(1 for a in m.GetAtoms() if a.GetAtomicNum() != 1)
    if schwer <= 2:  # Ethan, Ethin, Methanol: die Skelettformel ist nur ein Strich – Valenzstrich zeigen
        arten = ["valenzstrich"]
    bilder = []
    for art in arten:
        if art == "valenzstrich":
            bilder.append({"label": "Valenzstrichformel", "svg": Markup(valenzstrich_svg(b.smiles, f"Valenzstrichformel {b.name}"))})
        else:
            bilder.append({"label": "Skelettformel", "svg": Markup(skelett_svg(b.smiles, f"Skelettformel {b.name}"))})
    return {"bilder": bilder, "fehler": None}
