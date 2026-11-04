"""Sicheres Parsen von KI-Ausdrücken und Ausführen in einem eigenen Prozess mit Timeout.

parse_expr nutzt intern eval. Deshalb: 1) jeder Bezeichner im Text muss auf einer
Whitelist stehen, 2) eval sieht nur eine kleine Auswahl von SymPy-Namen, 3) gerechnet
wird in einem Arbeiterprozess, der bei Zeitüberschreitung beendet und neu gestartet wird.
"""
from __future__ import annotations

import multiprocessing as mp
import re
import threading

FUNKTIONEN = {
    "sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh", "tanh", "exp", "log", "ln",
    "sqrt", "Abs", "floor", "ceiling", "Piecewise", "Min", "Max", "pi", "E",
}
CHECK_EXTRA = {"integrate", "diff", "limit", "oo", "Sum", "Rational", "Eq", "solve", "factorial", "binomial"}
GRIECHISCH = {"alpha", "beta", "gamma", "delta", "phi", "theta", "lamda", "mu", "omega", "sigma", "tau", "rho"}

_VERBOTEN = re.compile(r"__|import|lambda|;|\n|\r|['\"`\\]|[A-Za-z_]\w*\s*\.")
_BEZ = re.compile(r"[A-Za-z_]\w*")
_VARIABLE = re.compile(r"^[A-Za-z](_?\d+)?$")


class Unsicher(ValueError):
    pass


def bezeichner_pruefen(text: str, erlaubt: set[str], variablen: set[str] | None = None) -> None:
    """Wirft Unsicher, wenn der Text nicht nur aus erlaubten Bezeichnern besteht.

    variablen=None: jede kurze Variable (a, x, k_1) und griechische Namen sind erlaubt.
    """
    if len(text) > 500:
        raise Unsicher("Ausdruck länger als 500 Zeichen")
    if _VERBOTEN.search(text):
        raise Unsicher(f"unzulässige Zeichen in {text!r}")
    for name in _BEZ.findall(text):
        if name in erlaubt:
            continue
        if variablen is None:
            if (_VARIABLE.match(name) or name in GRIECHISCH) and name != "e":
                continue
        elif name in variablen:
            continue
        raise Unsicher(f"unbekannter Name {name!r} in {text!r}")


def parsen(text: str, erlaubt: set[str], variablen: set[str] | None = None):
    """Nur im Arbeiterprozess aufrufen."""
    import sympy
    from sympy.parsing.sympy_parser import (convert_xor, implicit_multiplication_application,
                                            parse_expr, standard_transformations)

    bezeichner_pruefen(text, erlaubt, variablen)
    namen = {n: getattr(sympy, n) for n in (erlaubt - {"ln"}) if hasattr(sympy, n)}
    namen["ln"] = sympy.log
    glob = {"__builtins__": {}, "Integer": sympy.Integer, "Float": sympy.Float,
            "Symbol": sympy.Symbol, "Rational": sympy.Rational, **namen}
    lokal = {}
    for name in _BEZ.findall(text):
        if name not in glob:
            lokal[name] = sympy.Symbol(name, real=True)
    return parse_expr(text, local_dict=lokal, global_dict=glob,
                      transformations=standard_transformations + (implicit_multiplication_application, convert_xor))


# ---------------------------------------------------------------- Arbeiterprozess

def _arbeiter(verbindung):
    from . import aufgaben  # in diesem Prozess importiert (SymPy-lastig)
    while True:
        auftrag = verbindung.recv()
        if auftrag is None:
            return
        name, args = auftrag
        try:
            verbindung.send(("ok", getattr(aufgaben, name)(*args)))
        except Exception as e:  # noqa: BLE001 – jede Ausnahme ist ein Prüfergebnis
            verbindung.send(("fehler", f"{type(e).__name__}: {e}"))


class Zeitueberschreitung(Exception):
    pass


class Arbeiter:
    """Ein dauerhafter SymPy-Prozess; bei Zeitüberschreitung wird er ersetzt."""

    def __init__(self):
        self._sperre = threading.Lock()
        self._proz = None
        self._ltg = None

    def _starten(self):
        ktx = mp.get_context("spawn")
        self._ltg, kind = ktx.Pipe()
        self._proz = ktx.Process(target=_arbeiter, args=(kind,), daemon=True)
        self._proz.start()

    def _beenden(self):
        if self._proz is not None:
            self._proz.kill()
            self._proz.join(2)
        self._proz = None

    def ausfuehren(self, name: str, *args, timeout: float = 10.0):
        with self._sperre:
            if self._proz is None or not self._proz.is_alive():
                self._starten()
            self._ltg.send((name, args))
            # Der erste Auftrag zahlt den SymPy-Import mit, daher großzügiger.
            if not self._ltg.poll(timeout + (15 if not getattr(self, "_warm", False) else 0)):
                self._beenden()
                self._warm = False
                raise Zeitueberschreitung(name)
            self._warm = True
            status, wert = self._ltg.recv()
            if status == "fehler":
                raise RuntimeError(wert)
            return wert


ARBEITER = Arbeiter()
