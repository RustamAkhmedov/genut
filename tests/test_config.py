"""config.toml schreiben: wert_setzen und auswahl_ergaenzen (research.md R11)."""
import os
import tomllib

import pytest

from genut import config

VORLAGE = """\
# Kopfkommentar
[server]
host = "127.0.0.1"   # nur lokal erreichbar
port = 8765

[modell]
standard = "claude_code"   # Kommentar bleibt
auswahl = ["claude_code", "gemini"]   # KIs im Schalter

[claude_code]
befehl = "claude"
modell = ""           # leer = Standard

# Kommentar vor ollama
[ollama]
modell = "gemma3:4b"
"""

ALT_CLAUDE = """\
# gen_Ut – Version: Claude
[server]
port = 8765

[modell]
standard = "claude_code"
auswahl = ["claude_code", "gemini"]   # KIs im Schalter oben rechts

[gemini]
modell = ""
# Schlüssel NICHT hier, sondern in der Datei .env:  GEMINI_API_KEY=…

[funktionen]
lernplan = true   # ausschalten: lernplan = false
pruefung = true   # braucht die Claude-CLI
"""

ALT_GEMINI = """\
# gen_Ut – Version: Gemini
[modell]
standard = "gemini"
auswahl = ["gemini", "claude_code"]   # KIs im Schalter oben rechts

[ollama]
url = "http://localhost:11434"
modell = "gemma3:4b"  # ~4B-Vision-Modell
"""

ALT_LOKAL = """\
# gen_Ut – Version: Lokal (Ollama) – EXPERIMENTELL
[modell]
standard = "ollama"
auswahl = ["ollama", "gemini"]   # KIs im Schalter oben rechts

[pages]
aktiv = false
"""


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    pfad = tmp_path / "config.toml"
    monkeypatch.setenv("GENUT_CONFIG", str(pfad))
    config.laden.cache_clear()
    yield pfad
    config.laden.cache_clear()


def schreiben(pfad, text):
    pfad.write_bytes(text.encode("utf-8"))


def lesen(pfad):
    return pfad.read_bytes().decode("utf-8")


def test_zeile_ersetzen_alles_andere_bytegleich(cfg):
    schreiben(cfg, VORLAGE)
    assert config.laden()["ollama"]["modell"] == "gemma3:4b"
    config.wert_setzen("ollama", "modell", "qwen3-vl:8b")
    # nur [ollama] modell, nicht das gleichnamige [claude_code] modell
    assert lesen(cfg) == VORLAGE.replace('modell = "gemma3:4b"', 'modell = "qwen3-vl:8b"')
    assert config.laden()["ollama"]["modell"] == "qwen3-vl:8b"  # Zwischenspeicher geleert


def test_kommentar_hinter_dem_wert_bleibt(cfg):
    schreiben(cfg, VORLAGE)
    config.wert_setzen("modell", "standard", "gemini")
    assert lesen(cfg) == VORLAGE.replace('standard = "claude_code"', 'standard = "gemini"')


def test_raute_und_anfuehrungszeichen_im_wert(cfg):
    schreiben(cfg, '[claude_code]\nbefehl = "a # b"  # echt\n')
    wert = 'C:\\x\\"claude" # 1'
    config.wert_setzen("claude_code", "befehl", wert)
    assert lesen(cfg).endswith("  # echt\n")
    assert config.laden()["claude_code"]["befehl"] == wert


def test_zeile_am_ende_des_abschnitts_anlegen(cfg):
    schreiben(cfg, VORLAGE)
    config.wert_setzen("claude_code", "neu", "x")
    assert lesen(cfg) == VORLAGE.replace('# leer = Standard\n', '# leer = Standard\nneu = "x"\n')


def test_abschnitt_am_dateiende_anlegen(cfg):
    schreiben(cfg, VORLAGE)
    config.wert_setzen("gemini", "modell", "g")
    assert lesen(cfg) == VORLAGE + '\n[gemini]\nmodell = "g"\n'


def test_ohne_zeilenende_und_ohne_datei(cfg):
    config.wert_setzen("modell", "standard", "gemini")
    assert lesen(cfg) == '[modell]\nstandard = "gemini"\n'
    schreiben(cfg, "[modell]")
    config.wert_setzen("modell", "standard", "ollama")
    assert lesen(cfg) == '[modell]\nstandard = "ollama"\n'


def test_windows_zeilenenden_bleiben(cfg):
    text = VORLAGE.replace("\n", "\r\n")
    schreiben(cfg, text)
    config.wert_setzen("modell", "standard", "gemini")
    config.wert_setzen("gemini", "modell", "g")
    assert lesen(cfg) == text.replace('standard = "claude_code"', 'standard = "gemini"') + '\r\n[gemini]\r\nmodell = "g"\r\n'


def test_liste_schreiben_auch_mehrzeilig(cfg):
    schreiben(cfg, VORLAGE)
    config.wert_setzen("modell", "auswahl", ["ollama", "gemini"])
    assert lesen(cfg) == VORLAGE.replace('["claude_code", "gemini"]', '["ollama", "gemini"]')
    schreiben(cfg, '[modell]\nauswahl = [\n  "gemini",  # [x]\n]  # Ende\nstandard = "gemini"\n')
    config.wert_setzen("modell", "auswahl", ["gemini", "ollama"])
    assert lesen(cfg) == '[modell]\nauswahl = ["gemini", "ollama"]  # Ende\nstandard = "gemini"\n'


def test_ungueltiges_ergebnis_wird_nicht_geschrieben(cfg):
    text = 'modell = { standard = "gemini" }\n'
    schreiben(cfg, text)
    with pytest.raises(ValueError):
        config.wert_setzen("modell", "standard", "ollama")
    assert lesen(cfg) == text


@pytest.mark.skipif(os.name == "nt", reason="Dateirechte nur unter Unix")
def test_atomar_ohne_reste_und_rechte_bleiben(cfg):
    schreiben(cfg, VORLAGE)
    cfg.chmod(0o644)
    config.wert_setzen("modell", "standard", "gemini")
    assert cfg.stat().st_mode & 0o777 == 0o644
    assert [p.name for p in cfg.parent.iterdir()] == ["config.toml"]


@pytest.mark.parametrize("alt, erwartet", [
    (ALT_CLAUDE, ["claude_code", "gemini", "ollama"]),
    (ALT_GEMINI, ["gemini", "claude_code", "ollama"]),
    (ALT_LOKAL, ["ollama", "gemini", "claude_code"]),
], ids=["claude", "gemini", "lokal"])
def test_auswahl_ergaenzen_alte_versionen(cfg, alt, erwartet):
    schreiben(cfg, alt)
    standard = tomllib.loads(alt)["modell"]["standard"]
    sicherung = cfg.with_name("config.toml.bak")
    assert config.auswahl_ergaenzen() == erwartet[2:]
    assert config.laden()["modell"] == {"standard": standard, "auswahl": erwartet}
    assert lesen(sicherung) == alt

    neu = lesen(cfg)
    sicherung.unlink()
    assert config.auswahl_ergaenzen() == []
    assert lesen(cfg) == neu and not sicherung.exists()


def test_auswahl_ergaenzen_behaelt_fremde_ki(cfg):
    schreiben(cfg, '[modell]\nauswahl = ["openai_kompatibel"]\n')
    config.auswahl_ergaenzen()
    assert config.laden()["modell"]["auswahl"] == ["openai_kompatibel", "claude_code", "gemini", "ollama"]
