import random

import pytest

from genut.funktionen.ki_einrichtung.daten import Rechnerprofil, modelle_laden
from genut.funktionen.ki_einrichtung.modellwahl import keins_gut, vorschlaege

KLEIN, MITTEL, GROSS = (m.name for m in modelle_laden())  # Bedarf 6, 10, 14 GB
RANG = {"zu_gross": 0, "langsam": 1, "gut": 2}


def profil(ram, grafik="keine", grafik_gb=0, frei=None, system="linux"):
    if grafik == "apple":
        grafik_gb, system = ram, "macos"
    return Rechnerprofil(ram_gb=ram, grafik=grafik, grafik_gb=grafik_gb, frei_gb=frei, system=system)


def vorgewaehlt(liste):
    namen = [v.name for v in liste if v.vorgewaehlt]
    assert len(namen) == 1
    return namen[0]


@pytest.mark.parametrize("ram, grafik, grafik_gb, urteile, wahl", [
    # ohne Grafikkarte
    (8, "keine", 0, ["zu_gross", "zu_gross", "zu_gross"], KLEIN),
    (16, "keine", 0, ["langsam", "langsam", "zu_gross"], KLEIN),
    (32, "keine", 0, ["langsam", "langsam", "langsam"], KLEIN),
    # mit Grafikkarte
    (8, "nvidia", 8, ["gut", "zu_gross", "zu_gross"], KLEIN),
    (16, "nvidia", 4, ["langsam", "langsam", "zu_gross"], KLEIN),
    (16, "nvidia", 12, ["gut", "gut", "zu_gross"], MITTEL),
    (32, "nvidia", 8, ["gut", "langsam", "langsam"], KLEIN),
    (32, "nvidia", 16, ["gut", "gut", "gut"], GROSS),
    (8, "amd", 6, ["gut", "zu_gross", "zu_gross"], KLEIN),
    (16, "amd", 10, ["gut", "gut", "zu_gross"], MITTEL),
    (32, "amd", 24, ["gut", "gut", "gut"], GROSS),
    # Apple Silicon: gemeinsamer Speicher mindestens Bedarf + 4
    (8, "apple", 8, ["zu_gross", "zu_gross", "zu_gross"], KLEIN),
    (16, "apple", 16, ["gut", "gut", "zu_gross"], MITTEL),
    (32, "apple", 32, ["gut", "gut", "gut"], GROSS),
])
def test_tabelle(ram, grafik, grafik_gb, urteile, wahl):
    liste = vorschlaege(profil(ram, grafik, grafik_gb))
    assert [v.name for v in liste] == [KLEIN, MITTEL, GROSS]
    assert [v.urteil for v in liste] == urteile
    assert vorgewaehlt(liste) == wahl
    assert keins_gut(liste) == ("gut" not in urteile)


@pytest.mark.parametrize("p, index, teile", [
    (profil(8, "nvidia", 4), 1,
     ["braucht 14 GB Arbeitsspeicher, du hast 8 GB", "10 GB Grafikspeicher, du hast 4 GB"]),
    (profil(32, "nvidia", 4), 1, ["braucht 10 GB Grafikspeicher, du hast 4 GB", "32 GB"]),
    (profil(32, "amd", 12), 1, ["braucht 10 GB Grafikspeicher, du hast 12 GB"]),
    (profil(16), 0, ["ohne passende Grafikkarte", "16 GB, nötig sind 10 GB"]),
    (profil(8, "apple"), 0, ["braucht 10 GB Arbeitsspeicher, du hast 8 GB"]),
    (profil(16, "apple"), 1, ["braucht 14 GB gemeinsamen Speicher, du hast 16 GB"]),
    (profil(8, "nvidia", 9.96), 1, ["du hast 9,9 GB"]),
])
def test_begruendung(p, index, teile):
    satz = vorschlaege(p)[index].begruendung
    assert satz.endswith(".")
    for teil in teile:
        assert teil in satz


@pytest.mark.parametrize("frei, warnungen", [
    (None, [False, False, False]),
    (0, [True, True, True]),
    (5.3, [False, True, True]),  # genau Download + 2 reicht
    (9, [False, False, True]),
    (100, [False, False, False]),
])
def test_platz_warnung(frei, warnungen):
    assert [v.platz_warnung for v in vorschlaege(profil(16, frei=frei))] == warnungen


def test_vorhanden():
    liste = vorschlaege(profil(16), vorhandene=iter([MITTEL, "llava:7b"]))
    assert [v.vorhanden for v in liste] == [False, True, False]
    assert not any(v.vorhanden for v in vorschlaege(profil(16)))


def zufallsprofil(rng):
    def groesse():  # auch ganze Zahlen, damit die Grenzwerte getroffen werden
        return rng.choice([rng.randint(0, 64), round(rng.uniform(0, 64), 2)])

    grafik = rng.choice(["nvidia", "amd", "apple", "keine"])
    return profil(groesse(), grafik, 0 if grafik == "keine" else groesse(),
                  frei=rng.choice([None, groesse()]))


def test_eigenschaften():
    rng = random.Random(20261125)
    for _ in range(2000):
        p = zufallsprofil(rng)
        liste = vorschlaege(p)
        assert len(liste) == 3, p
        wahl = vorgewaehlt(liste)
        gute = [v.name for v in liste if v.urteil == "gut"]
        assert wahl == (gute[-1] if gute else KLEIN), p
        for v in liste:
            if v.urteil == "gut":
                assert p.grafik != "keine", p
                reserve = 4 if p.grafik == "apple" else 0
                assert v.bedarf_gb + reserve <= p.grafik_gb, p
            elif v.urteil == "langsam":
                assert v.bedarf_gb + 4 <= p.ram_gb, p
        # größerer Bedarf nie besser bewertet
        raenge = [RANG[v.urteil] for v in liste]
        assert raenge == sorted(raenge, reverse=True), p
        # mehr Speicher nie schlechter bewertet
        plus = rng.uniform(0, 32)
        if p.grafik == "apple":
            mehr = [profil(p.ram_gb + plus, "apple")]
        else:
            mehr = [p.model_copy(update={"ram_gb": p.ram_gb + plus})]
            if p.grafik != "keine":
                mehr.append(p.model_copy(update={"grafik_gb": p.grafik_gb + plus}))
        for m in mehr:
            assert all(RANG[b.urteil] >= a for a, b in zip(raenge, vorschlaege(m))), (p, m)
