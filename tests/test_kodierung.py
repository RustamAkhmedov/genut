"""Windows: Python liest und schreibt dort ohne Angabe nicht UTF-8, sondern cp1252. seite.js ist darin nicht einmal
lesbar, und Zeichen wie → oder ✓ lassen sich nicht schreiben. Deshalb muss jeder Textzugriff im Programm
ausdrücklich `encoding` angeben. Die ganze Suite läuft außerdem mit erzwungener ASCII-Kodierung durch:
    PYTHONUTF8=0 PYTHONCOERCECLOCALE=0 LC_ALL=C python -m pytest -q
"""
import ast
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent


def _kw(call: ast.Call, name: str):
    return next((k.value for k in call.keywords if k.arg == name), None)


def _textmodus(call: ast.Call, pos: int) -> bool:
    modus = call.args[pos] if len(call.args) > pos else _kw(call, "mode")
    if modus is None:
        return True                                   # Standard "r" bzw. "w+b" (NamedTemporaryFile → unten)
    return isinstance(modus, ast.Constant) and "b" not in str(modus.value)


def stellen_ohne_encoding(quelle: str) -> list[int]:
    zeilen = []
    for n in ast.walk(ast.parse(quelle)):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
        ziel = f.value.id if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) else ""
        hat = _kw(n, "encoding") is not None
        if name in ("read_text", "write_text") and not hat:
            zeilen.append(n.lineno)
        elif name in ("run", "Popen", "check_output") and ziel == "subprocess":
            text = _kw(n, "text") or _kw(n, "universal_newlines")
            if isinstance(text, ast.Constant) and text.value and not hat:
                zeilen.append(n.lineno)
        elif name == "NamedTemporaryFile" and n.args and _textmodus(n, 0) and not hat:
            zeilen.append(n.lineno)
        elif name in ("open", "fdopen") and ziel in ("", "os", "io") and _textmodus(n, 1) and not hat:
            zeilen.append(n.lineno)
    return zeilen


def test_waechter_findet_fehlendes_encoding():
    beispiel = ('p.read_text()\np.write_text("x")\nsubprocess.run(c, text=True)\n'
                'tempfile.NamedTemporaryFile("w")\nos.fdopen(fd, "w")\nopen(p)\n'
                'p.read_text(encoding="utf-8")\nopen(p, "rb")\nImage.open(p)\nsubprocess.run(c)\n')
    assert stellen_ohne_encoding(beispiel) == [1, 2, 3, 4, 5, 6]


def test_programm_gibt_ueberall_utf8_an():
    fehler = [f"{p.relative_to(WURZEL)}:{z}" for p in sorted((WURZEL / "genut").rglob("*.py"))
              for z in stellen_ohne_encoding(p.read_text(encoding="utf-8"))]
    assert not fehler, "Textzugriff ohne encoding (unter Windows cp1252): " + ", ".join(fehler)


def test_start_bat_schaltet_utf8_modus_ein():
    assert "set PYTHONUTF8=1" in (WURZEL / "setup.ps1").read_text(encoding="utf-8")
