"""Grundgerüst für entfernbare Module (genut/funktionen/__init__.py)."""
import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from genut import funktionen
from genut.config import laden

WURZEL = Path(__file__).resolve().parent.parent

MODUL = '''
from fastapi import APIRouter
NAME = "testmodul"
def aktiv(cfg):
    return bool(cfg["funktionen"].get("testmodul"))
def einhaengen(app):
    r = APIRouter()
    @r.get("/api/testmodul/ping")
    def ping():
        return {"ok": True}
    app.include_router(r)
'''


def _config(monkeypatch, tmp_path, text):
    cfg = tmp_path / "config.toml"
    cfg.write_text(text, encoding="utf-8")
    monkeypatch.setenv("GENUT_CONFIG", str(cfg))
    laden.cache_clear()


@pytest.fixture
def suchpfad(tmp_path, monkeypatch):
    """Zusätzlicher Suchpfad mit einem Test-Modul; räumt sys.modules danach auf."""
    ordner = tmp_path / "module"
    (ordner / "testmodul").mkdir(parents=True)
    (ordner / "testmodul" / "__init__.py").write_text(MODUL, encoding="utf-8")
    monkeypatch.setattr(funktionen, "__path__", [str(ordner), *funktionen.__path__])
    yield ordner
    for n in [n for n in sys.modules if n.startswith("genut.funktionen.testmodul")]:
        del sys.modules[n]
    laden.cache_clear()


def test_modul_eingehaengt_und_in_ki(suchpfad, monkeypatch, tmp_path):
    from genut.server import app as echte_app

    _config(monkeypatch, tmp_path, "[funktionen]\ntestmodul = true\n")
    assert "testmodul" in funktionen.vorhanden()
    app = FastAPI()
    funktionen.einhaengen_alle(app)
    assert TestClient(app).get("/api/testmodul/ping").json() == {"ok": True}
    ki = TestClient(echte_app).get("/api/ki").json()
    assert "testmodul" in ki["module"] and ki["funktionen"]["testmodul"] is True


def test_ausgeschaltet_404_ohne_neue_app(suchpfad, monkeypatch, tmp_path):
    from genut.server import app as echte_app

    _config(monkeypatch, tmp_path, "[funktionen]\ntestmodul = true\n")
    app = FastAPI()
    funktionen.einhaengen_alle(app)
    c, ki = TestClient(app), TestClient(echte_app)
    assert c.get("/api/testmodul/ping").status_code == 200
    _config(monkeypatch, tmp_path, "[funktionen]\ntestmodul = false\n")
    assert c.get("/api/testmodul/ping").status_code == 404
    assert "testmodul" not in ki.get("/api/ki").json()["module"]
    _config(monkeypatch, tmp_path, "[funktionen]\ntestmodul = true\n")
    assert c.get("/api/testmodul/ping").status_code == 200
    assert "testmodul" in ki.get("/api/ki").json()["module"]


def test_fehlendes_modul(monkeypatch, tmp_path):
    from genut.server import app as echte_app

    leer = tmp_path / "leer"
    leer.mkdir()
    monkeypatch.setattr(funktionen, "__path__", [str(leer)])
    app = FastAPI()
    assert funktionen.einhaengen_alle(app) == [] and funktionen.vorhanden() == []
    assert TestClient(app).get("/api/testmodul/ping").status_code == 404
    assert TestClient(echte_app).get("/api/ki").json()["module"] == []


def test_defektes_modul_bricht_start_ab(suchpfad):
    (suchpfad / "testmodul" / "__init__.py").write_text("raise ValueError('kaputt')", encoding="utf-8")
    with pytest.raises(RuntimeError, match="testmodul.*kaputt"):
        funktionen.einhaengen_alle(FastAPI())


def test_pruefung_ohne_modul_kein_schritt_keine_route(monkeypatch, tmp_path):
    """Gelöschter Ordner genut/funktionen/pruefung/: auch mit pruefung = true weder Modul noch Route (404)."""
    from genut.server import app as echte_app

    _config(monkeypatch, tmp_path, "[funktionen]\npruefung = true\n")
    ohne = tmp_path / "ohne"
    ohne.mkdir()
    for n in funktionen.vorhanden():
        if n != "pruefung":
            (ohne / n).symlink_to(Path(funktionen.__path__[0]) / n, target_is_directory=True)
    monkeypatch.setattr(funktionen, "__path__", [str(ohne)])
    assert "pruefung" not in funktionen.vorhanden()
    app = FastAPI()
    funktionen.einhaengen_alle(app)
    assert TestClient(app).get("/api/projekte/x/pruefungen").status_code == 404
    assert TestClient(app).post("/api/projekte/x/pruefungen", json={}).status_code in (404, 405)
    ki = TestClient(echte_app).get("/api/ki").json()
    assert "pruefung" not in ki["module"]  # kein Modul, also lädt die UI kein pruefung.js und es gibt keinen Schritt
    laden.cache_clear()


def test_ohne_modul_austausch_keine_route(monkeypatch, tmp_path):
    """Gelöschter Ordner genut/funktionen/austausch/: auch mit austausch = true weder Modul noch Route (404)."""
    from genut.server import app as echte_app

    _config(monkeypatch, tmp_path, "[funktionen]\naustausch = true\n")
    ohne = tmp_path / "ohne"
    ohne.mkdir()
    for n in funktionen.vorhanden():
        if n != "austausch":
            (ohne / n).symlink_to(Path(funktionen.__path__[0]) / n, target_is_directory=True)
    monkeypatch.setattr(funktionen, "__path__", [str(ohne)])
    assert "austausch" not in funktionen.vorhanden()
    app = FastAPI()
    funktionen.einhaengen_alle(app)
    assert TestClient(app).get("/api/austausch/herkunft").status_code == 404
    assert TestClient(app).post("/api/austausch/import").status_code == 404
    ki = TestClient(echte_app).get("/api/ki").json()
    assert "austausch" not in ki["module"]  # kein Modul, also lädt die UI kein austausch.js
    laden.cache_clear()


BEFEHL = '''
def befehle(subparsers):
    p = subparsers.add_parser("testbefehl", help="Befehl aus dem Testmodul")
    p.set_defaults(fn=lambda args: print("testbefehl lief"))
'''


def _hilfe(capsys) -> str:
    from genut.__main__ import main

    with pytest.raises(SystemExit) as e:
        main(["--help"])
    assert e.value.code == 0
    return capsys.readouterr().out


def test_ki_bereit_ohne_quelle_unbekannt():
    assert funktionen.ki_bereit("claude_code") is None


def test_ki_bereit_mit_quelle():
    funktionen.ki_zustand_quelle(lambda name: {"claude_code": True, "gemini": False}.get(name))
    assert funktionen.ki_bereit("claude_code") is True
    assert funktionen.ki_bereit("gemini") is False
    assert funktionen.ki_bereit("openai_kompatibel") is None


def test_ki_bereit_fehler_der_quelle_unbekannt():
    def kaputt(name):
        raise OSError("keine CLI")

    funktionen.ki_zustand_quelle(kaputt)
    assert funktionen.ki_bereit("claude_code") is None


def test_modul_mit_befehlen_in_der_hilfe(suchpfad, monkeypatch, tmp_path, capsys):
    from genut.__main__ import main

    (suchpfad / "testmodul" / "__init__.py").write_text(MODUL + BEFEHL, encoding="utf-8")
    _config(monkeypatch, tmp_path, "[funktionen]\ntestmodul = true\n")
    assert "testbefehl" in _hilfe(capsys)
    main(["testbefehl"])
    assert "testbefehl lief" in capsys.readouterr().out
    _config(monkeypatch, tmp_path, "[funktionen]\ntestmodul = false\n")
    assert "testbefehl" not in _hilfe(capsys)


def test_modul_ohne_befehle_stoert_nicht(suchpfad, monkeypatch, tmp_path, capsys):
    _config(monkeypatch, tmp_path, "[funktionen]\ntestmodul = true\n")
    assert "testmodul" in funktionen.aktive(laden())
    assert "serve" in _hilfe(capsys)


# ---------------------------------------------------------------- ohne Modul ki_einrichtung (005b, FR-020, SC-007)

# Eigener Prozess: nur dort wird der echte Server ohne das Modul gebaut (die App dieses Prozesses hat es schon).
OHNE_KI_EINRICHTUNG = '''
import sys
from genut import funktionen
funktionen.__path__ = [sys.argv[1]]

from fastapi.testclient import TestClient
from genut.__main__ import main
from genut.server import app

c = TestClient(app)
assert c.get("/").status_code == 200
assert c.get("/api/ki/zustaende").status_code == 404
module = c.get("/api/ki").json()["module"]
assert "ki_einrichtung" not in module and "pruefung" in module, module

# Schalter wie früher: ohne Erkennung wird jede bekannte KI angenommen, Unbekanntes nicht
for name in ("gemini", "ollama", "claude_code"):
    r = c.put("/api/ki", json={"standard": name})
    assert r.status_code == 200 and r.json()["standard"] == name, (name, r.text)
assert c.put("/api/ki", json={"standard": "gibtsnicht"}).status_code == 400

r = c.get("/api/pruefung/verfuegbar")
assert r.status_code == 200 and r.json() == {"verfuegbar": False}, r.text
b = "/api/projekte/x/pruefungen"
for methode, pfad in [("GET", b), ("POST", b), ("GET", b + "/pr-00000000"), ("POST", b + "/pr-00000000/antwort"),
                      ("POST", b + "/pr-00000000/weiter"), ("POST", b + "/pr-00000000/beenden"),
                      ("DELETE", b + "/pr-00000000")]:
    r = c.request(methode, pfad, json={"themen": ["t-00000001"], "fragen": 3, "text": "x"})
    assert r.status_code == 404, (methode, pfad, r.status_code)

try:
    main(["ki", "status"])
except SystemExit as e:
    assert e.code == 2, e.code
else:
    raise AssertionError("`genut ki` ist noch bekannt")
assert not [n for n in sys.modules if n.startswith("genut.funktionen.ki_einrichtung")]
print("OHNE-MODUL-OK")
'''


def test_ohne_modul_ki_einrichtung(tmp_path):
    ohne = tmp_path / "ohne"
    ohne.mkdir()
    for n in funktionen.vorhanden():
        if n != "ki_einrichtung":
            (ohne / n).symlink_to(Path(funktionen.__path__[0]) / n, target_is_directory=True)
    cfg = tmp_path / "config.toml"
    cfg.write_text('[funktionen]\npruefung = "auto"\n', encoding="utf-8")
    env = {**os.environ, "GENUT_CONFIG": str(cfg), "GENUT_PROJEKTE": str(tmp_path / "projekte")}
    p = subprocess.run([sys.executable, "-c", OHNE_KI_EINRICHTUNG, str(ohne)], cwd=WURZEL, env=env,
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert p.returncode == 0 and "OHNE-MODUL-OK" in p.stdout, p.stdout + p.stderr


def _importe(datei: Path):
    """Alle importierten Modulnamen einer Datei, relative Importe aufgelöst."""
    paket = list(datei.relative_to(WURZEL).parts[:-1])
    for k in ast.walk(ast.parse(datei.read_text(encoding="utf-8"), str(datei))):
        if isinstance(k, ast.Import):
            yield from (a.name for a in k.names)
        elif isinstance(k, ast.ImportFrom):
            basis = paket[: len(paket) - k.level + 1] if k.level else []
            ziel = ".".join(basis + ([k.module] if k.module else []))
            yield ziel
            yield from (f"{ziel}.{a.name}" for a in k.names)


def test_niemand_importiert_ki_einrichtung():
    """Nur so lässt sich das Modul löschen. Seine eigenen Tests werden mit ihm gelöscht."""
    eigene = [WURZEL / "genut" / "funktionen" / "ki_einrichtung", WURZEL / "tests" / "funktionen" / "ki_einrichtung"]
    dateien = [d for o in ("genut", "tests", "werkzeuge") for d in sorted((WURZEL / o).rglob("*.py"))
               if not any(d.is_relative_to(e) for e in eigene)]
    assert WURZEL / "genut" / "server.py" in dateien
    treffer = [f"{d.relative_to(WURZEL)}: {n}" for d in dateien for n in _importe(d)
               if f"{n}.".startswith("genut.funktionen.ki_einrichtung.")]
    assert treffer == []
