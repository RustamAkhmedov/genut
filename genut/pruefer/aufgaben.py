"""Rechenaufträge, die im Arbeiterprozess laufen (siehe sandbox.Arbeiter).

Jede Funktion bekommt nur einfache Datentypen und gibt (ok, meldung) bzw. Listen zurück.
"""
from __future__ import annotations

import random
import re
import warnings

import numpy as np
import sympy
from sympy.printing.jscode import jscode

from .sandbox import CHECK_EXTRA, FUNKTIONEN, parsen

CHECK_NAMEN = FUNKTIONEN | CHECK_EXTRA


def _wert(text: str):
    a = parsen(text, CHECK_NAMEN)
    return a.doit() if hasattr(a, "doit") else a


def _num_gleich(a, b, rel=1e-9) -> bool:
    try:
        fa, fb = complex(sympy.N(a, 30)), complex(sympy.N(b, 30))
    except (TypeError, ValueError):
        return False
    return abs(fa - fb) <= rel * max(1.0, abs(fa), abs(fb))


def _gleich(a, b) -> bool:
    try:
        if sympy.simplify(a - b) == 0:
            return True
    except Exception:  # noqa: BLE001
        pass
    frei = sorted((a - b).free_symbols, key=str)
    if not frei:
        return _num_gleich(a, b)
    rnd = random.Random(42)
    getroffen = 0
    for _ in range(20):
        belegung = {s: sympy.Float(rnd.uniform(-3, 3)) for s in frei}
        try:
            va, vb = a.subs(belegung), b.subs(belegung)
            fa, fb = complex(sympy.N(va)), complex(sympy.N(vb))
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if not (np.isfinite(fa) and np.isfinite(fb)):
            continue
        if abs(fa - fb) > 1e-9 * max(1.0, abs(fa), abs(fb)):
            return False
        getroffen += 1
        if getroffen >= 5:
            return True
    return False


def _kurz(x) -> str:
    s = sympy.sstr(x)
    return s if len(s) < 120 else s[:117] + "…"


def check_gleich(ausdruck: str, erwartet: str):
    a, b = _wert(ausdruck), _wert(erwartet)
    if _gleich(a, b):
        return True, ""
    return False, f"angegeben {erwartet}, SymPy berechnet {_kurz(sympy.simplify(a))} für {ausdruck}"


def check_numerisch(ausdruck: str, erwartet: float, toleranz: float):
    a = _wert(ausdruck)
    try:
        wert = float(sympy.N(a))
    except TypeError:
        return False, f"{ausdruck} ergibt keine reelle Zahl ({_kurz(a)})"
    if abs(wert - erwartet) <= toleranz:
        return True, ""
    return False, f"angegeben {erwartet}, SymPy berechnet {wert:.6g} für {ausdruck} (Toleranz {toleranz})"


def check_loesungen(gleichungen: list[str], variablen: list[str], erwartet: list[dict]):
    for v in variablen:
        if not re.fullmatch(r"[A-Za-z](_?\d+)?", v):
            return False, f"ungültiger Variablenname {v!r}"
    syms = [sympy.Symbol(v, real=True) for v in variablen]
    namen = {str(s): s for s in syms}
    gl = []
    for g in gleichungen:
        e = parsen(g, CHECK_NAMEN)
        e = e.subs({s: namen[str(s)] for s in e.free_symbols if str(s) in namen})
        gl.append(e)
    loes = sympy.solve(gl, syms, dict=True)
    soll = []
    for d in erwartet:
        soll.append({namen[k]: _wert(v) for k, v in d.items() if k in namen})
    offen = list(loes)
    for s in soll:
        treffer = next((l for l in offen if set(l) >= set(s) and all(_gleich(l[k], s[k]) for k in s)), None)
        if treffer is None:
            return False, f"erwartete Lösung {_fmt(s)} ist keine Lösung; SymPy findet {_fmt_liste(loes)}"
        offen.remove(treffer)
    if offen:
        return False, f"Lösungen fehlen: SymPy findet zusätzlich {_fmt_liste(offen)}"
    return True, ""


def _fmt(d) -> str:
    return "{" + ", ".join(f"{k} = {_kurz(v)}" for k, v in d.items()) + "}"


def _fmt_liste(l) -> str:
    return "[" + "; ".join(_fmt(d) for d in l) + "]" if l else "keine Lösung"


# ---------------------------------------------------------------- Graphen

PARAM_NAME = re.compile(r"^([a-wyzA-Z]|[a-zA-Z]_[0-9])$")


def graph_pruefen(graph: dict):
    """Gibt (fehler: list[str], js: list[str|None]) zurück."""
    fehler: list[str] = []
    params = graph.get("parameter") or []
    pnamen = []
    for p in params:
        n = p["name"]
        if not PARAM_NAME.match(n) or n == "e":
            fehler.append(f"Parametername {n!r} unzulässig (ein Buchstabe außer x/e oder Buchstabe_Ziffer)")
            continue
        if not p["min"] < p["max"]:
            fehler.append(f"Parameter {n}: min muss kleiner als max sein")
        if not p["min"] <= p["start"] <= p["max"]:
            fehler.append(f"Parameter {n}: start liegt nicht zwischen min und max")
        if p["schritt"] <= 0 or (p["max"] - p["min"]) / p["schritt"] > 1000:
            fehler.append(f"Parameter {n}: schritt muss > 0 sein und höchstens 1000 Stufen ergeben")
        pnamen.append(n)
    x0, x1 = graph["x_min"], graph["x_max"]
    if not x0 < x1:
        fehler.append("x_min muss kleiner als x_max sein")
        return fehler, [None] * len(graph["funktionen"])
    if not graph["funktionen"]:
        fehler.append("Graph ohne Funktion")
    x = sympy.Symbol("x", real=True)
    psym = [sympy.Symbol(n, real=True) for n in pnamen]
    js: list[str | None] = []
    xs = np.linspace(x0, x1, 400)
    benutzt: set[str] = set()
    alle_geparst = True
    for i, f in enumerate(graph["funktionen"]):
        try:
            expr = parsen(f["ausdruck"], FUNKTIONEN, {"x", *pnamen})
        except Exception as e:  # noqa: BLE001
            fehler.append(f"Funktion {i + 1} ({f['ausdruck']}): {e}")
            js.append(None)
            alle_geparst = False
            continue
        benutzt |= {s.name for s in expr.free_symbols}
        fn = sympy.lambdify([x, *psym], expr, "numpy")
        varianten = [[p["start"] for p in params]]
        if params:
            varianten += [[p["min"] for p in params], [p["max"] for p in params]]
        schlecht = None
        for werte in varianten:
            with warnings.catch_warnings(), np.errstate(all="ignore"):
                warnings.simplefilter("ignore")
                try:
                    ys = np.asarray(fn(xs, *werte), dtype=complex) * np.ones_like(xs)
                except Exception as e:  # noqa: BLE001
                    schlecht = f"lässt sich nicht auswerten ({e})"
                    break
            gut = np.isfinite(ys) & (np.abs(ys.imag) < 1e-9)
            anteil = gut.mean()
            if anteil < 0.8:
                bel = ", ".join(f"{n}={w}" for n, w in zip(pnamen, werte))
                schlecht = (f"im Bereich [{x0}, {x1}]{' bei ' + bel if bel else ''} zu "
                            f"{round((1 - anteil) * 100)} % undefiniert – x_min/x_max oder Parameterbereich anpassen")
                break
        if schlecht:
            fehler.append(f"Funktion {i + 1} ({f['ausdruck']}) {schlecht}")
            js.append(None)
        else:
            js.append(jscode(expr))
    if alle_geparst:
        for n in pnamen:
            if n not in benutzt:
                fehler.append(f"Parameter {n} kommt in keiner Funktion vor – der Schieberegler hätte keine Wirkung. "
                              f"Parameter in einen Ausdruck einbauen oder entfernen.")
    fl = graph.get("flaeche")
    if fl and not (0 <= fl["funktion"] < len(graph["funktionen"]) and fl["von"] < fl["bis"]):
        fehler.append("flaeche: ungültiger Funktionsindex oder von >= bis")
    return fehler, js


def selbsttest():
    return True
from .fach import *  # noqa: F401,F403  Fach-Prüfungen im selben Arbeiterprozess
