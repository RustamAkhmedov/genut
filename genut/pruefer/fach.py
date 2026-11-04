"""Fach-Prüfungen: Einheiten (Physik), Reaktionsgleichungen (Chemie), SQL (DBI), Subnetze (NSCS).

Läuft im Arbeiterprozess (siehe sandbox.Arbeiter); jede Funktion gibt (ok, meldung) bzw. Daten zurück.
"""
from __future__ import annotations

import ipaddress
import re
import sqlite3
from collections import Counter
from fractions import Fraction

from .sandbox import FUNKTIONEN, Unsicher, bezeichner_pruefen

# ---------------------------------------------------------------- Einheiten (Physik)

EINHEIT_NAMEN = {"m", "cm", "mm", "km", "s", "ms", "min", "h", "kg", "g", "t", "N", "kN", "J", "kJ", "kWh",
                 "W", "kW", "Pa", "hPa", "bar", "V", "A", "mA", "Ohm", "C", "Hz", "K", "mol", "L", "mL", "eV"}


def _einheiten():
    from sympy.physics import units as u
    return {
        "m": u.meter, "cm": u.centimeter, "mm": u.millimeter, "km": u.kilometer,
        "s": u.second, "ms": u.millisecond, "min": u.minute, "h": u.hour,
        "kg": u.kilogram, "g": u.gram, "t": 1000 * u.kilogram,
        "N": u.newton, "kN": 1000 * u.newton, "J": u.joule, "kJ": 1000 * u.joule, "kWh": 1000 * u.watt * u.hour,
        "W": u.watt, "kW": 1000 * u.watt, "Pa": u.pascal, "hPa": 100 * u.pascal, "bar": 100000 * u.pascal,
        "V": u.volt, "A": u.ampere, "mA": u.ampere / 1000, "Ohm": u.ohm, "C": u.coulomb, "Hz": u.hertz,
        "K": u.kelvin, "mol": u.mole, "L": u.liter, "mL": u.liter / 1000, "eV": u.electronvolt,
    }


def _einheit_parsen(text: str):
    import sympy
    from sympy.parsing.sympy_parser import convert_xor, parse_expr, standard_transformations

    bezeichner_pruefen(text, EINHEIT_NAMEN | FUNKTIONEN, variablen=set())
    namen = {n: getattr(sympy, n) for n in FUNKTIONEN - {"ln"} if hasattr(sympy, n)}
    namen["ln"] = sympy.log
    glob = {"__builtins__": {}, "Integer": sympy.Integer, "Float": sympy.Float, "Rational": sympy.Rational, **namen}
    return parse_expr(text, local_dict=_einheiten(), global_dict=glob,
                      transformations=standard_transformations + (convert_xor,))


def _si(x):
    from sympy.physics import units as u
    return u.convert_to(x, [u.meter, u.kilogram, u.second, u.ampere, u.kelvin, u.mole]).simplify()


def check_einheit(ausdruck: str, erwartet: str, toleranz: float = 0.001):
    import sympy
    from sympy.physics.units import Quantity

    a, b = _einheit_parsen(ausdruck), _einheit_parsen(erwartet)
    sa, sb = _si(a), _si(b)
    verh = sympy.simplify(sa / sb)
    if verh.atoms(Quantity) or verh.free_symbols:
        return False, (f"Einheit passt nicht: {ausdruck} ergibt {sympy.sstr(sa)} (SI), "
                       f"angegeben {erwartet} = {sympy.sstr(sb)} (SI)")
    try:
        r = float(sympy.N(verh))
    except (TypeError, ValueError):
        return None, f"nicht auswertbar: {sympy.sstr(verh)}"
    if abs(r - 1) <= max(toleranz, 1e-9):
        return True, ""
    return False, (f"angegeben {erwartet}, berechnet {sympy.sstr(sympy.N(sa, 6))} (in SI-Basiseinheiten) "
                   f"für {ausdruck} – Abweichung {abs(r - 1) * 100:.2g} %")


# ---------------------------------------------------------------- Reaktionsgleichungen (Chemie)

ELEMENTE = set("""H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr
Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re
Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh
Fl Mc Lv Ts Og D""".split())

_PFEIL = re.compile(r"\s*(?:<=>>|<<=>|<=>|<->|->|<-|=)(?:\[[^\]]*\]){0,2}\s*")
_ZUSTAND = re.compile(r"\s*\((?:s|l|g|aq|fl)\)$")
_LADUNG = re.compile(r"(?:\^\{?([0-9]*)([+-])\}?|(?<![0-9^])([+-]))$")
_KOEFF = re.compile(r"^(\d+(?:[.,]\d+)?(?:/\d+)?)\s*(?=[A-Z(\[e])")


def _formel_atome(f: str) -> Counter:
    """Atome einer Summenformel ohne Ladung, z. B. Ca(OH)2, [Cu(NH3)4]SO4, CuSO4*5H2O."""
    gesamt: Counter = Counter()
    for teil in re.split(r"[*·.]", f):
        teil = teil.strip()
        if not teil:
            continue
        m = re.match(r"^(\d+)(.*)$", teil)
        faktor = int(m.group(1)) if m else 1
        rest = m.group(2) if m else teil
        atome, pos = _gruppe(rest, 0)
        if pos != len(rest):
            raise ValueError(f"Formel nicht lesbar: {f!r} (bei {rest[pos:]!r})")
        for k, v in atome.items():
            gesamt[k] += v * faktor
    return gesamt


def _gruppe(s: str, i: int) -> tuple[Counter, int]:
    c: Counter = Counter()
    while i < len(s):
        ch = s[i]
        if ch in "([":
            inner, i = _gruppe(s, i + 1)
            if i >= len(s) or s[i] not in ")]":
                raise ValueError(f"Klammer nicht geschlossen in {s!r}")
            i += 1
            m = re.match(r"\d+", s[i:])
            n = int(m.group(0)) if m else 1
            i += len(m.group(0)) if m else 0
            for k, v in inner.items():
                c[k] += v * n
        elif ch in ")]":
            return c, i
        else:
            m = re.match(r"([A-Z][a-z]?)(\d*)", s[i:])
            if not m:
                raise ValueError(f"unerwartetes Zeichen {ch!r} in {s!r}")
            el = m.group(1)
            if el not in ELEMENTE:
                raise ValueError(f"unbekanntes Element {el!r}")
            c[el] += int(m.group(2) or 1)
            i += len(m.group(0))
    return c, i


def _teilchen(t: str) -> tuple[Fraction, Counter, int]:
    t = re.sub(r"\s+[v^]$", "", t.strip())  # mhchem: v = Niederschlag, ^ = Gas
    t = _ZUSTAND.sub("", t)
    m = _KOEFF.match(t)
    koeff = Fraction(m.group(1).replace(",", ".")) if m else Fraction(1)
    if m:
        t = t[m.end():].strip()
    if t in ("e-", "e^-", "e^{-}"):
        return koeff, Counter(), -1
    ladung = 0
    lm = _LADUNG.search(t)
    if lm:
        zahl, vorz = (lm.group(1), lm.group(2)) if lm.group(2) else ("", lm.group(3))
        ladung = (int(zahl) if zahl else 1) * (1 if vorz == "+" else -1)
        t = t[:lm.start()]
    t = t.replace("{", "").replace("}", "").replace("_", "")
    return koeff, _formel_atome(t), ladung


def _seite(text: str) -> tuple[Counter, Fraction]:
    atome: Counter = Counter()
    ladung = Fraction(0)
    for t in re.split(r"\s\+\s", f" {text.strip()} "):
        if not t.strip():
            continue
        k, a, q = _teilchen(t)
        for el, n in a.items():
            atome[el] += k * n
        ladung += k * q
    return atome, ladung


def check_reaktion(gleichung: str):
    g = gleichung.strip()
    if g.startswith("\\ce{") and g.endswith("}"):
        g = g[4:-1]
    teile = _PFEIL.split(g, maxsplit=1)
    if len(teile) != 2:
        return False, f"kein Reaktionspfeil (->, <=>) in {gleichung!r}"
    try:
        la, lq = _seite(teile[0])
        ra, rq = _seite(teile[1])
    except ValueError as e:
        return False, f"Reaktionsgleichung {gleichung!r}: {e}"
    probleme = []
    for el in sorted(set(la) | set(ra)):
        if la[el] != ra[el]:
            probleme.append(f"{el}: links {la[el]}, rechts {ra[el]}")
    if lq != rq:
        probleme.append(f"Ladung: links {lq}, rechts {rq}")
    if probleme:
        return False, f"Gleichung {gleichung!r} nicht ausgeglichen – " + "; ".join(probleme)
    return True, ""


# ---------------------------------------------------------------- Strukturformeln (Chemie)

def _ohne_ladung(f: str) -> str:
    f = f.strip()
    if f.startswith("\\ce{") and f.endswith("}"):
        f = f[4:-1]
    f = _LADUNG.sub("", f.strip())
    return f.replace("{", "").replace("}", "").replace("_", "")


def check_struktur(smiles: str, summenformel: str, halbstruktur: str | None = None):
    """SMILES lesbar? Passen Summenformel und Halbstrukturformel (Atome) zum SMILES?"""
    from ..render.struktur import StrukturFehler, atome
    try:
        ist = atome(smiles)
    except StrukturFehler as e:
        return False, str(e)
    probleme = []
    for art, formel in (("Summenformel", summenformel), ("Halbstrukturformel", halbstruktur)):
        if not formel:
            continue
        roh = _ohne_ladung(formel)
        roh = re.sub(r"[-=#≡–—]", "", roh)  # Bindungsstriche der Kurzschreibweise
        try:
            soll = _formel_atome(roh)
        except ValueError as e:
            probleme.append(f"{art} {formel!r}: {e}")
            continue
        if soll != ist:
            diff = "; ".join(f"{el}: {soll[el]} statt {ist[el]}" for el in sorted(set(soll) | set(ist)) if soll[el] != ist[el])
            probleme.append(f"{art} {formel!r} passt nicht zum SMILES {smiles!r} – {diff}")
    if probleme:
        return False, " · ".join(probleme)
    return True, ""


# ---------------------------------------------------------------- SQL (DBI)

MAX_ZEILEN = 200


def _sql_verbindung() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")

    def waechter(aktion, *_):
        # keine fremden Datenbankdateien öffnen
        return sqlite3.SQLITE_DENY if aktion in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH) else sqlite3.SQLITE_OK

    con.set_authorizer(waechter)
    return con


def sql_ausfuehren(schema_sql: str, abfrage: str) -> dict:
    """Führt Beispieldaten + Abfrage in einer leeren In-Memory-Datenbank aus."""
    con = _sql_verbindung()
    try:
        try:
            con.executescript(schema_sql)
        except sqlite3.Error as e:
            return {"spalten": [], "zeilen": [], "fehler": f"Fehler in den Beispieldaten (schema_sql): {e}"}
        try:
            stmts = [x for x in _sql_anweisungen(abfrage)]
            cur = None
            for st in stmts:
                cur = con.execute(st)
            if cur is None or cur.description is None:
                return {"spalten": [], "zeilen": [], "fehler": None}
            spalten = [d[0] for d in cur.description]
            zeilen = [list(z) for z in cur.fetchmany(MAX_ZEILEN)]
            return {"spalten": spalten, "zeilen": zeilen, "fehler": None}
        except sqlite3.Error as e:
            return {"spalten": [], "zeilen": [], "fehler": f"Fehler in der Abfrage: {e}"}
    finally:
        con.close()


def _sql_anweisungen(text: str) -> list[str]:
    """Teilt an ; außerhalb von Zeichenketten (für Abfragen mit mehreren Anweisungen)."""
    teile, cur, q = [], "", None
    for ch in text:
        if q:
            cur += ch
            if ch == q:
                q = None
        elif ch in "'\"":
            q = ch
            cur += ch
        elif ch == ";":
            if cur.strip():
                teile.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        teile.append(cur)
    return teile


def _sql_wert(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _zelle_gleich(a: str, b: str) -> bool:
    if a.strip() == b.strip():
        return True
    try:
        return abs(float(a.replace(",", ".")) - float(b.replace(",", "."))) <= 1e-6 * max(1, abs(float(a.replace(",", "."))))
    except ValueError:
        return a.strip().lower() == b.strip().lower() and a.strip().lower() == "null"


def check_sql(schema_sql: str, abfrage: str, erwartet: list[list[str]], reihenfolge: bool = False):
    r = sql_ausfuehren(schema_sql, abfrage)
    if r["fehler"]:
        return False, r["fehler"]
    ist = [[_sql_wert(v) for v in z] for z in r["zeilen"]]
    soll = [[str(v) for v in z] for z in erwartet]
    if len(ist) != len(soll):
        return False, f"Abfrage liefert {len(ist)} Zeilen, erwartet {len(soll)}. Erste Zeilen: {ist[:5]}"
    if not reihenfolge:
        ist, soll = sorted(ist), sorted(soll)
    for zi, zs in zip(ist, soll):
        if len(zi) != len(zs) or not all(_zelle_gleich(a, b) for a, b in zip(zi, zs)):
            return False, f"Ergebnis weicht ab: Abfrage liefert {zi}, erwartet {zs} (alle Zeilen: {ist[:8]})"
    return True, ""


# ---------------------------------------------------------------- Subnetze (NSCS)

def subnetz_werte(netz: str) -> dict:
    iface = ipaddress.ip_interface(netz.strip())
    n = iface.network
    p = n.prefixlen
    w: dict = {"netzadresse": str(n.network_address), "praefix": p}
    if n.version == 4:
        w["maske"] = str(n.netmask)
        w["broadcast"] = str(n.broadcast_address)
        if p <= 30:
            w["hosts"] = n.num_addresses - 2
            w["erster_host"] = str(n.network_address + 1)
            w["letzter_host"] = str(n.broadcast_address - 1)
        else:
            w["hosts"] = n.num_addresses
            w["erster_host"] = str(n.network_address)
            w["letzter_host"] = str(n.broadcast_address)
    else:
        w["hosts"] = n.num_addresses
        w["erster_host"] = str(n.network_address + (1 if p < 128 else 0))
        w["letzter_host"] = str(n.broadcast_address)
    return w


def _ip_gleich(a: str, b: str) -> bool:
    try:
        return ipaddress.ip_address(a.strip().split("/")[0]) == ipaddress.ip_address(b.strip().split("/")[0])
    except ValueError:
        return a.strip() == b.strip()


def check_subnetz(netz: str, erwartet: dict):
    try:
        w = subnetz_werte(netz)
    except ValueError as e:
        return False, f"{netz!r} ist keine gültige Adresse mit Präfix ({e})"
    probleme = []
    for k, soll in erwartet.items():
        if soll is None:
            continue
        if k not in w:
            probleme.append(f"{k} gibt es bei IPv{ipaddress.ip_interface(netz).version} nicht")
            continue
        ist = w[k]
        ok = (int(soll) == ist) if k in ("hosts", "praefix") else _ip_gleich(str(soll), str(ist))
        if not ok:
            probleme.append(f"{k}: angegeben {soll}, richtig {ist}")
    if probleme:
        return False, f"Subnetz {netz}: " + "; ".join(probleme)
    return True, ""


__all__ = ["check_einheit", "check_reaktion", "check_struktur", "check_sql", "sql_ausfuehren", "check_subnetz", "subnetz_werte",
           "Unsicher"]
