"""Fach-Prüfungen: Einheiten, Reaktionsgleichungen, SQL, Subnetze (laufen im Arbeiterprozess)."""
import pytest

from genut.pruefer.sandbox import ARBEITER


def a(name, *args):
    return ARBEITER.ausfuehren(name, *args)


# ---------------------------------------------------------------- Einheiten
@pytest.mark.parametrize("ausdruck,erwartet,ok", [
    ("12*m/s * 3*s", "36*m", True),
    ("90*km/h * 20*min", "30*km", True),
    ("90*km/h", "25*m/s", True),
    ("2*kg * 9.81*m/s**2", "19.62*N", True),
    ("12*m/s * 3*s", "36*s", False),          # falsche Einheit
    ("12*m/s * 3*s", "38*m", False),          # falscher Wert
    ("230*V * 2*A * 3*h", "1.38*kWh", True),
])
def test_einheit(ausdruck, erwartet, ok):
    erg, meldung = a("check_einheit", ausdruck, erwartet, 0.001)
    assert erg is ok, meldung


def test_einheit_toleranz_und_meldung():
    ok, _ = a("check_einheit", "100*m / (9.58*s)", "10.44*m/s", 0.001)
    assert ok
    ok, m = a("check_einheit", "12*m/s * 3*s", "36*s", 0.001)
    assert not ok and "Einheit passt nicht" in m


def test_einheit_unsicher():
    with pytest.raises(RuntimeError):
        a("check_einheit", "__import__('os')", "1*m", 0.001)


# ---------------------------------------------------------------- Reaktionen
@pytest.mark.parametrize("gl,ok", [
    ("2H2 + O2 -> 2H2O", True),
    ("H2 + O2 -> H2O", False),
    ("CH4 + 2O2 -> CO2 + 2H2O", True),
    ("Fe^3+ + 3OH- -> Fe(OH)3", True),
    ("Fe^{3+} + 2OH^- -> Fe(OH)3", False),       # Ladung + Atome falsch
    ("Ca(OH)2 + 2HCl -> CaCl2 + 2H2O", True),
    ("CuSO4*5H2O -> CuSO4 + 5H2O", True),
    ("2Na(s) + Cl2(g) -> 2NaCl(s)", True),
    ("Zn -> Zn^2+ + 2e-", True),
    ("N2 + 3H2 <=> 2NH3", True),
    ("\\ce{2H2 + O2 -> 2H2O}", True),
    ("SO4^2- + Ba^2+ -> BaSO4", True),
])
def test_reaktion(gl, ok):
    erg, m = a("check_reaktion", gl)
    assert erg is ok, m


def test_reaktion_meldungen():
    ok, m = a("check_reaktion", "H2 + O2 -> H2O")
    assert not ok and "O: links 2, rechts 1" in m
    ok, m = a("check_reaktion", "Xy + O2 -> XyO2")
    assert not ok and "unbekanntes Element" in m
    ok, m = a("check_reaktion", "H2 + O2")
    assert not ok and "Reaktionspfeil" in m


# ---------------------------------------------------------------- SQL
SCHEMA = """CREATE TABLE schueler(id INTEGER PRIMARY KEY, name TEXT, klasse TEXT, note INTEGER);
INSERT INTO schueler VALUES (1,'Huber','4A',2),(2,'Maier','4A',1),(3,'Gruber','4B',3);"""


def test_sql_ausfuehren():
    r = a("sql_ausfuehren", SCHEMA, "SELECT klasse, COUNT(*) AS n FROM schueler GROUP BY klasse ORDER BY klasse")
    assert r["fehler"] is None and r["spalten"] == ["klasse", "n"] and r["zeilen"] == [["4A", 2], ["4B", 1]]
    r = a("sql_ausfuehren", SCHEMA, "SELECT * FROM gibtsnicht")
    assert "no such table" in r["fehler"]
    r = a("sql_ausfuehren", "CREATE TABLE x(", "SELECT 1")
    assert "Beispieldaten" in r["fehler"]


def test_sql_kein_attach(tmp_path):
    ziel = tmp_path / "boese.db"
    r = a("sql_ausfuehren", f"ATTACH DATABASE '{ziel}' AS b;", "SELECT 1")
    assert r["fehler"] and not ziel.exists()


def test_check_sql():
    q = "SELECT name FROM schueler WHERE klasse = '4A'"
    assert a("check_sql", SCHEMA, q, [["Maier"], ["Huber"]], False)[0] is True
    ok, m = a("check_sql", SCHEMA, q, [["Maier"], ["Huber"]], True)   # Reihenfolge verlangt → Huber zuerst
    assert ok is False
    ok, m = a("check_sql", SCHEMA, q, [["Maier"]], False)
    assert ok is False and "2 Zeilen" in m
    assert a("check_sql", SCHEMA, "SELECT AVG(note) FROM schueler", [["2"]], False)[0] is True


# ---------------------------------------------------------------- Subnetze
def test_subnetz():
    ok, m = a("check_subnetz", "192.168.10.77/26", {"netzadresse": "192.168.10.64", "broadcast": "192.168.10.127",
                                                      "erster_host": "192.168.10.65", "letzter_host": "192.168.10.126",
                                                      "hosts": 62, "maske": "255.255.255.192", "praefix": 26})
    assert ok, m
    ok, m = a("check_subnetz", "192.168.10.77/26", {"broadcast": "192.168.10.255", "hosts": 64})
    assert not ok and "broadcast" in m and "hosts" in m
    ok, m = a("check_subnetz", "2001:db8:abcd:12::1/64", {"netzadresse": "2001:0db8:abcd:0012::", "hosts": 2 ** 64})
    assert ok, m
    ok, m = a("check_subnetz", "999.1.1.1/24", {"praefix": 24})
    assert not ok


@pytest.mark.parametrize("gl", ["Fe^3+ + 3OH- -> Fe(OH)3 v", "CaCO3 ->[\\Delta] CaO + CO2 ^", "Zn + 2HCl -> ZnCl2 + H2 ^"])
def test_reaktion_mhchem_zeichen(gl):
    ok, m = a("check_reaktion", gl)
    assert ok, m


# ---------------------------------------------------------------- Strukturformeln (Chemie)
@pytest.mark.parametrize("smiles,summe,halb,ok", [
    ("CCO", "C2H6O", "CH3-CH2-OH", True),
    ("CCO", "C2H5OH", None, True),                      # andere Schreibweise, gleiche Atome
    ("CC(=O)OCC", "C4H8O2", "CH3-COO-CH2-CH3", True),
    ("CC(C)C", "C4H10", "CH3-CH(CH3)-CH3", True),
    ("C#C", "C2H2", "HC#CH", True),
    ("CC(=O)[O-]", "C2H3O2^-", "CH3-COO^-", True),
    ("c1ccccc1", "C6H6", None, True),
    ("CCO", "C2H4O", None, False),                      # Summenformel passt nicht
    ("CCO", "C2H6O", "CH3-CH2-CH2-OH", False),          # Halbstrukturformel passt nicht
    ("C1CC", "C3H6", None, False),                      # SMILES kaputt
])
def test_struktur(smiles, summe, halb, ok):
    erg, m = a("check_struktur", smiles, summe, halb)
    assert erg is ok, m


def test_struktur_meldung():
    ok, m = a("check_struktur", "CCO", "C2H4O", None)
    assert not ok and "H: 4 statt 6" in m
