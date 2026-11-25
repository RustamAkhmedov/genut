"""modelle.toml: die mitgelieferte Datei ist gültig, jede verletzte Regel scheitert (data-model.md)."""
import pytest

from genut.funktionen.ki_einrichtung.daten import modelle_laden

GUT = [("klein", "a", 1.0, 4), ("mittel", "b", 2.0, 8), ("groß", "c", 3.0, 12)]


def _datei(tmp_path, eintraege):
    pfad = tmp_path / "modelle.toml"
    pfad.write_text("".join(f'[[modell]]\nstufe = "{s}"\nname = "{n}"\ndownload_gb = {d}\nbedarf_gb = {b}\n'
                            for s, n, d, b in eintraege), encoding="utf-8")
    return pfad


def _mit(i, eintrag):
    return GUT[:i] + [eintrag] + GUT[i + 1:]


def test_mitgelieferte_datei():
    assert [(m.name, m.download_gb, m.bedarf_gb) for m in modelle_laden()] == [
        ("gemma3:4b", 3.3, 6), ("qwen3-vl:8b", 6.1, 10), ("gemma3:12b", 8.1, 14)]


def test_gueltige_testdatei(tmp_path):
    assert len(modelle_laden(_datei(tmp_path, GUT))) == 3


@pytest.mark.parametrize("eintraege", [
    GUT[:2],
    GUT + [("riesig", "d", 4.0, 16)],
    [],
    _mit(1, ("mittel", "a", 2.0, 8)),    # Name doppelt
    _mit(0, ("klein", "a", 0, 4)),       # download_gb = 0
    _mit(0, ("klein", "a", -1, 4)),
    _mit(0, ("klein", "a", 4.0, 4)),     # download_gb = bedarf_gb
    _mit(0, ("klein", "a", 5.0, 4)),
    [GUT[1], GUT[0], GUT[2]],            # nicht aufsteigend
    _mit(1, ("mittel", "b", 2.0, 4)),    # gleicher Bedarf
    _mit(0, ("klein", "", 1.0, 4)),
])
def test_verletzte_regel(tmp_path, eintraege):
    with pytest.raises(ValueError):
        modelle_laden(_datei(tmp_path, eintraege))


@pytest.mark.parametrize("text", [
    "kein toml [",
    '[[modell]]\nname = "a"\n',  # Felder fehlen
])
def test_kaputte_datei(tmp_path, text):
    pfad = tmp_path / "modelle.toml"
    pfad.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        modelle_laden(pfad)
