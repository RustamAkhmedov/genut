"""Setup-Skripte (setup.sh, setup.ps1, setup.bat): Syntax, Schalter, keine alten Versionsnamen, --hilfe ohne Seiteneffekte."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parent.parent
SH = WURZEL / "setup.sh"
PS1 = WURZEL / "setup.ps1"
BAT = WURZEL / "setup.bat"
ALTE_VERSIONEN = ("versionen/claude.toml", "versionen/gemini.toml", "versionen/lokal.toml")


def lesen(pfad: Path) -> str:
    return pfad.read_text(encoding="utf-8-sig")


@pytest.mark.parametrize("pfad", [SH, PS1, BAT])
def test_skript_existiert(pfad):
    assert pfad.is_file(), f"{pfad.name} fehlt"


@pytest.mark.parametrize("pfad", [SH, PS1, BAT])
def test_keine_alten_versionsdateien(pfad):
    text = lesen(pfad)
    for alt in ALTE_VERSIONEN:
        assert alt not in text, f"{pfad.name} verweist noch auf {alt}"


@pytest.mark.parametrize(
    "pfad, schalter",
    [
        (SH, ("--nur", "--standard")),
        (PS1, ("-Nur", "-Standard")),
        (BAT, ("-Nur", "-Standard")),
    ],
)
def test_schalter_bekannt(pfad, schalter):
    text = lesen(pfad)
    for s in schalter:
        assert s in text, f"{pfad.name} kennt {s} nicht"


def test_setup_sh_hilfe_kennt_alle_schalter():
    text = lesen(SH)
    assert "--hilfe" in text and "--nur" in text and "--standard" in text


def test_setup_ps1_hilfe_kennt_alle_schalter():
    text = lesen(PS1)
    assert "-Hilfe" in text and "-Nur" in text and "-Standard" in text


def test_setup_bat_reicht_argumente_weiter():
    text = lesen(BAT)
    assert "setup.ps1" in text and "%*" in text
    rem_zeilen = [z for z in text.splitlines() if z.lower().startswith("rem")]
    rem_text = "\n".join(rem_zeilen)
    assert "-Nur" in rem_text and "-Standard" in rem_text


@pytest.mark.skipif(shutil.which("bash") is None, reason="kein bash (z. B. Windows)")
def test_setup_sh_syntax_ok():
    ergebnis = subprocess.run(["bash", "-n", str(SH)], capture_output=True, text=True, encoding="utf-8")
    assert ergebnis.returncode == 0, ergebnis.stderr


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh nicht installiert")
def test_setup_ps1_parst_ohne_fehler():
    pfad = str(PS1).replace("'", "''")
    befehl = (
        "$fehler = $null; $t = $null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{pfad}', [ref]$t, [ref]$fehler) | Out-Null; "
        "if ($fehler) { $fehler | ForEach-Object { $_.Message }; exit 1 }"
    )
    ergebnis = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", befehl], capture_output=True, text=True, encoding="utf-8"
    )
    assert ergebnis.returncode == 0, ergebnis.stdout + ergebnis.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="kein bash (z. B. Windows)")
def test_setup_sh_hilfe_legt_nichts_an(tmp_path):
    kopie = tmp_path / "setup.sh"
    shutil.copy(SH, kopie)
    vorher = {p.relative_to(tmp_path) for p in tmp_path.rglob("*")}

    ergebnis = subprocess.run(
        ["bash", str(kopie), "--hilfe"], capture_output=True, text=True, encoding="utf-8", cwd=tmp_path
    )

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert "--nur" in ergebnis.stdout and "--standard" in ergebnis.stdout
    nachher = {p.relative_to(tmp_path) for p in tmp_path.rglob("*")}
    assert nachher == vorher, f"--hilfe hat Dateien angelegt: {sorted(nachher - vorher)}"


def test_setup_sh_klammert_variablen_vor_sonderzeichen():
    """Die Bash 3.2 von macOS zählt das erste Byte eines folgenden Nicht-ASCII-Zeichens (z. B. “ oder …) zum
    Variablennamen: "„$X“" bricht mit „unbound variable“ ab. Dort muss ${X} stehen."""
    text = (Path(__file__).resolve().parent.parent / "setup.sh").read_text(encoding="utf-8")
    funde = [f"Zeile {n}: {m.group(0)}" for n, zeile in enumerate(text.splitlines(), 1)
             for m in re.finditer(r"\$[A-Za-z_][A-Za-z0-9_]*(?=[^\x00-\x7f])", zeile)]
    assert not funde, funde
