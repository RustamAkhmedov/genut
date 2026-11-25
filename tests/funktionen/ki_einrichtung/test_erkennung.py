"""Erkennung der KIs (research.md R4, R5): jede Zustandsregel, Zwischenspeicher, Parallelität, SC-004.
Kein echter Unterprozess, kein echtes Netz: `subprocess.run`, `shutil.which` und `httpx.MockTransport`."""
from __future__ import annotations

import json
import subprocess
import threading
import time

import httpx
import pytest

from genut.config import laden
from genut.funktionen.ki_einrichtung import erkennung

SCHLUESSEL = "AIzaGEHEIM-test-1234567890"


class Welt:
    """Gefälschte Umgebung: Programme im PATH, Antworten der CLI, von Google und von Ollama."""

    def __init__(self):
        self.pfad: dict[str, str] = {}             # Befehl → gefundener Pfad (shutil.which)
        self.claude = (0, json.dumps({"loggedIn": True}))  # (Exit-Code, stdout) oder eine Ausnahme
        self.aufrufe: list[list[str]] = []
        self.run_kw: list[dict] = []
        self.schluessel: str | None = SCHLUESSEL
        self.google: int | Exception = 200
        self.ollama: list[str] | int | Exception = ["gemma3:4b"]
        self.anfragen: list[httpx.Request] = []
        self.haengen = threading.Event()           # gesetzt = Prüfungen hängen bis `loslassen`
        self.loslassen = threading.Event()

    def which(self, befehl, *a, **kw):
        return self.pfad.get(befehl)

    def run(self, cmd, **kw):
        self.aufrufe.append(list(cmd))
        self.run_kw.append(kw)
        if self.haengen.is_set():
            self.loslassen.wait(30)               # hängt und ignoriert das Zeitlimit
        if isinstance(self.claude, BaseException):
            raise self.claude
        code, aus = self.claude
        return subprocess.CompletedProcess(cmd, code, aus, "")

    def http(self, request: httpx.Request) -> httpx.Response:
        self.anfragen.append(request)
        if self.haengen.is_set():
            self.loslassen.wait(30)
        if request.url.host == "generativelanguage.googleapis.com":
            if isinstance(self.google, Exception):
                raise self.google
            daten = {"models": [{"name": "models/gemini-3-flash"}]} if self.google == 200 else {"error": {}}
            return httpx.Response(self.google, json=daten)
        if request.url.path == "/api/tags":
            if isinstance(self.ollama, Exception):
                raise self.ollama
            if isinstance(self.ollama, int):
                return httpx.Response(self.ollama)
            return httpx.Response(200, json={"models": [{"name": n, "model": n, "size": 1} for n in self.ollama]})
        return httpx.Response(404)


def _config(pfad, auswahl=("claude_code", "gemini", "ollama"), befehl="claude", modell="gemma3:4b"):
    liste = ", ".join(f'"{n}"' for n in auswahl)
    pfad.write_text(f'[modell]\nstandard = "gemini"\nauswahl = [{liste}]\n'
                    f'[claude_code]\nbefehl = "{befehl}"\n'
                    f'[ollama]\nurl = "http://localhost:11434"\nmodell = "{modell}"\n', encoding="utf-8")
    laden.cache_clear()


@pytest.fixture
def welt(tmp_path, monkeypatch):
    w = Welt()
    heim = tmp_path / "heim"
    heim.mkdir()
    monkeypatch.setenv("HOME", str(heim))
    monkeypatch.setenv("USERPROFILE", str(heim))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("GENUT_CONFIG", str(tmp_path / "config.toml"))
    _config(tmp_path / "config.toml")
    monkeypatch.setattr(erkennung.shutil, "which", w.which)
    monkeypatch.setattr(erkennung.subprocess, "run", w.run)
    monkeypatch.setattr(erkennung._gemini, "schluessel", lambda: w.schluessel)
    monkeypatch.setattr(erkennung, "transport", httpx.MockTransport(w.http))
    monkeypatch.setattr(erkennung, "_windows", lambda: False)
    w.pfad["claude"] = "/usr/bin/claude"
    w.pfad["ollama"] = "/usr/bin/ollama"
    w.tmp = tmp_path
    w.heim = heim
    erkennung.leeren()
    yield w
    w.loslassen.set()
    erkennung.leeren()
    laden.cache_clear()


def _sauber(z):
    """Ursache ohne Pfad und ohne Schlüssel; nichts im ganzen Zustand verrät den Schlüssel."""
    assert "/" not in z.ursache and "\\" not in z.ursache
    assert SCHLUESSEL not in z.model_dump_json()
    if z.zustand == "bereit":
        assert z.ursache == "" and z.aktion == ""
    return z


def _eins(name):
    return _sauber(erkennung.pruefen(name))


# ---------------------------------------------------------------- Claude


def test_claude_angemeldet_bereit(welt):
    z = _eins("claude_code")
    assert (z.zustand, z.ursache, z.aktion) == ("bereit", "", "")
    assert welt.aufrufe == [["/usr/bin/claude", "auth", "status", "--json"]]
    assert welt.run_kw[0]["timeout"] == 5


def test_claude_befehl_aus_config_hat_vorrang(welt):
    _config(welt.tmp / "config.toml", befehl="/opt/mein/claude")
    welt.pfad["/opt/mein/claude"] = "/opt/mein/claude"
    assert _eins("claude_code").zustand == "bereit"
    assert welt.aufrufe[0][0] == "/opt/mein/claude"


def test_claude_befehl_aus_config_fehlt_dann_path(welt):
    _config(welt.tmp / "config.toml", befehl="/weg/claude")
    assert _eins("claude_code").zustand == "bereit"
    assert welt.aufrufe[0][0] == "/usr/bin/claude"


def test_claude_unter_local_bin(welt):
    del welt.pfad["claude"]
    datei = welt.heim / ".local" / "bin" / "claude"
    datei.parent.mkdir(parents=True)
    datei.write_text("#!/bin/sh\n")
    datei.chmod(0o755)
    assert _eins("claude_code").zustand == "bereit"
    assert welt.aufrufe[0][0] == str(datei)
    assert erkennung.claude_befehl() == str(datei)


def test_claude_unter_windows(welt, monkeypatch):
    monkeypatch.setattr(erkennung, "_windows", lambda: True)
    del welt.pfad["claude"]
    datei = welt.heim / ".local" / "bin" / "claude.exe"
    datei.parent.mkdir(parents=True)
    datei.write_bytes(b"")
    assert _eins("claude_code").zustand == "bereit"
    assert welt.aufrufe[0][0] == str(datei)


def test_claude_fehlt(welt):
    del welt.pfad["claude"]
    z = _eins("claude_code")
    assert (z.zustand, z.aktion) == ("nicht_eingerichtet", "einrichten")
    assert welt.aufrufe == []
    assert erkennung.claude_befehl() is None


@pytest.mark.parametrize("code, aus", [
    (1, json.dumps({"loggedIn": False, "authMethod": "none"})),
    (0, json.dumps({"logged_in": False})),
    (0, "Hinweis vorneweg\n" + json.dumps({"loggedIn": False}) + "\n"),
])
def test_claude_nicht_angemeldet_unabhaengig_vom_exit_code(welt, code, aus):
    welt.claude = (code, aus)
    z = _eins("claude_code")
    assert (z.zustand, z.ursache, z.aktion) == ("problem", "nicht angemeldet", "anmelden")


@pytest.mark.parametrize("code, aus", [
    (0, json.dumps({"logged_in": True})),
    (1, json.dumps({"loggedIn": True})),
    (1, "error: unknown command 'auth'"),   # ältere CLI: Rückfallregel
    (0, "kein JSON"),
    (0, ""),
    (2, json.dumps([1, 2])),
])
def test_claude_rueckfall_und_angemeldet(welt, code, aus):
    welt.claude = (code, aus)
    assert _eins("claude_code").zustand == "bereit"


def test_claude_zeitueberschreitung(welt):
    welt.claude = subprocess.TimeoutExpired(["claude"], 5)
    z = _eins("claude_code")
    assert (z.zustand, z.ursache) == ("problem", "keine Antwort")


def test_claude_verschwindet_beim_start(welt):
    welt.claude = FileNotFoundError("/usr/bin/claude")
    z = _eins("claude_code")
    assert (z.zustand, z.aktion) == ("nicht_eingerichtet", "einrichten")


# ---------------------------------------------------------------- Gemini


def test_gemini_ohne_schluessel(welt):
    welt.schluessel = None
    z = _eins("gemini")
    assert (z.zustand, z.aktion) == ("nicht_eingerichtet", "schluessel")
    assert welt.anfragen == []


def test_gemini_bereit_ueber_modellliste(welt):
    assert _eins("gemini").zustand == "bereit"
    [r] = welt.anfragen
    assert r.method == "GET"
    assert r.url.path == "/v1beta/models"
    assert r.url.params["pageSize"] == "200"
    assert r.headers["x-goog-api-key"] == SCHLUESSEL
    assert SCHLUESSEL not in str(r.url)


@pytest.mark.parametrize("status", [400, 401, 403])
def test_gemini_schluessel_abgelehnt(welt, status):
    welt.google = status
    z = _eins("gemini")
    assert (z.zustand, z.ursache, z.aktion) == ("problem", "Schlüssel wird nicht akzeptiert", "schluessel")


@pytest.mark.parametrize("fehler", [httpx.ConnectError("weg"), httpx.ReadTimeout("zu langsam"), 500, 503])
def test_gemini_keine_verbindung(welt, fehler):
    welt.google = fehler
    z = _eins("gemini")
    assert (z.zustand, z.ursache) == ("problem", "keine Verbindung")


def test_gemini_ungespeicherten_schluessel_pruefen(welt):
    welt.schluessel = None
    assert erkennung.gemini_schluessel_pruefen("  neu-123  ") == "ok"
    assert welt.anfragen[-1].headers["x-goog-api-key"] == "neu-123"
    welt.google = 400
    assert erkennung.gemini_schluessel_pruefen("neu-123") == "abgelehnt"
    welt.google = httpx.ConnectError("weg")
    assert erkennung.gemini_schluessel_pruefen("neu-123") == "keine_verbindung"
    assert erkennung.gemini_schluessel_pruefen("kaputt\nzeile") == "keine_verbindung"


def test_gemini_zeitlimit(welt):
    erkennung.gemini_schluessel_pruefen("x")
    assert welt.anfragen[0].extensions["timeout"]["read"] == 5


# ---------------------------------------------------------------- Ollama


def test_ollama_bereit(welt):
    assert _eins("ollama").zustand == "bereit"
    [r] = welt.anfragen
    assert (r.method, str(r.url)) == ("GET", "http://localhost:11434/api/tags")
    assert r.extensions["timeout"]["connect"] == 1


def test_ollama_modell_ohne_tag(welt):
    _config(welt.tmp / "config.toml", modell="gemma3")
    welt.ollama = ["gemma3:latest"]
    assert _eins("ollama").zustand == "bereit"


def test_ollama_modell_fehlt(welt):
    welt.ollama = ["llama3:8b"]
    z = _eins("ollama")
    assert (z.zustand, z.ursache, z.aktion) == ("nicht_eingerichtet", "Modell gemma3:4b fehlt", "einrichten")


@pytest.mark.parametrize("fehler", [httpx.ConnectError("aus"), httpx.ConnectTimeout("aus"), 500])
def test_ollama_laeuft_nicht(welt, fehler):
    welt.ollama = fehler
    z = _eins("ollama")
    assert (z.zustand, z.ursache, z.aktion) == ("problem", "Ollama läuft nicht", "starten")


def test_ollama_laeuft_nicht_windows(welt, monkeypatch):
    monkeypatch.setattr(erkennung, "_windows", lambda: True)
    del welt.pfad["ollama"]
    welt.ollama = httpx.ConnectError("aus")
    exe = welt.tmp / "appdata" / "Programs" / "Ollama" / "ollama.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(welt.tmp / "appdata"))
    assert _eins("ollama").aktion == "starten"
    assert erkennung.ollama_programm() == str(exe)


def test_ollama_fehlt(welt):
    del welt.pfad["ollama"]
    welt.ollama = httpx.ConnectError("aus")
    z = _eins("ollama")
    assert (z.zustand, z.aktion) == ("nicht_eingerichtet", "einrichten")
    assert erkennung.ollama_programm() is None


def test_ollama_modelle_liste(welt):
    welt.ollama = ["a:1", "b:2"]
    assert [m["name"] for m in erkennung.ollama_modelle()] == ["a:1", "b:2"]
    welt.ollama = httpx.ConnectError("aus")
    assert erkennung.ollama_modelle() is None


# ---------------------------------------------------------------- Ablauf


def test_reihenfolge_und_unbekannte_namen(welt):
    _config(welt.tmp / "config.toml", auswahl=("ollama", "openai_kompatibel", "claude_code", "ollama"))
    assert [z.name for z in erkennung.zustaende()] == ["ollama", "claude_code"]
    assert erkennung.bereit("openai_kompatibel") is None
    assert erkennung.bereit("ollama") is True


def test_bereit_prueft_nur_diese_ki(welt):
    del welt.pfad["claude"]
    assert erkennung.bereit("claude_code") is False
    assert welt.anfragen == []
    assert erkennung.bereit("gemini") is True
    assert welt.aufrufe == []


def test_zwischenspeicher(welt, monkeypatch):
    uhr = [1000.0]
    monkeypatch.setattr(erkennung, "_uhr", lambda: uhr[0])
    erste = erkennung.zustaende()
    assert len(welt.aufrufe) == 1 and len(welt.anfragen) == 2
    uhr[0] += 14
    assert erkennung.zustaende() == erste
    assert erkennung.bereit("claude_code") is True
    assert len(welt.aufrufe) == 1 and len(welt.anfragen) == 2   # zweiter Aufruf ohne Unterprozess
    uhr[0] += 2                                                  # 16 s: abgelaufen
    erkennung.zustaende()
    assert len(welt.aufrufe) == 2 and len(welt.anfragen) == 4


def test_neu_umgeht_speicher_und_leeren(welt):
    erkennung.zustaende()
    welt.claude = (1, json.dumps({"loggedIn": False}))
    assert erkennung.zustaende()[0].zustand == "bereit"          # noch gespeichert
    assert erkennung.zustaende(neu=True)[0].ursache == "nicht angemeldet"
    assert len(welt.aufrufe) == 2
    welt.claude = (0, json.dumps({"loggedIn": True}))
    erkennung.leeren()
    assert erkennung.bereit("claude_code") is True
    assert len(welt.aufrufe) == 3


def test_parallel_drei_haengende_pruefungen(welt):
    welt.haengen.set()
    beginn = time.monotonic()
    zustaende = erkennung.zustaende()
    dauer = time.monotonic() - beginn
    welt.loslassen.set()
    assert dauer < 6
    assert [(z.name, z.zustand) for z in zustaende] == [
        ("claude_code", "problem"), ("gemini", "problem"), ("ollama", "problem")]
    assert [z.ursache for z in zustaende] == ["keine Antwort", "keine Verbindung", "keine Antwort"]
    for z in zustaende:
        _sauber(z)


def test_gleichzeitige_aufrufer_pruefen_nur_einmal(welt, monkeypatch):
    echt = welt.run

    def langsam(cmd, **kw):
        time.sleep(0.3)
        return echt(cmd, **kw)

    monkeypatch.setattr(erkennung.subprocess, "run", langsam)
    ergebnisse = []
    threads = [threading.Thread(target=lambda: ergebnisse.append(erkennung.bereit("claude_code")))
               for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert ergebnisse == [True] * 5
    assert len(welt.aufrufe) == 1


def test_fehler_in_pruefung(welt, monkeypatch):
    def kaputt(cfg):
        raise RuntimeError(f"Absturz mit {SCHLUESSEL} in /geheim/pfad")

    monkeypatch.setitem(erkennung._PRUEFUNGEN, "gemini", kaputt)
    z = _sauber(erkennung.zustand("gemini"))
    assert (z.zustand, z.ursache) == ("problem", "Prüfung fehlgeschlagen")


def test_erste_pruefung_fuellt_speicher(welt):
    erkennung.erste_pruefung()
    assert len(welt.aufrufe) == 1
    erkennung.zustaende()
    assert len(welt.aufrufe) == 1


def test_keine_generierung_sc004(welt):
    """Über alle Zustände: nur Status- und Listenabfragen, nie ein Generierungs-Endpunkt oder `claude -p`."""
    for claude in [(0, json.dumps({"loggedIn": True})), (1, json.dumps({"loggedIn": False})), (1, "unbekannt")]:
        for google in (200, 401, httpx.ConnectError("weg")):
            for ollama in (["gemma3:4b"], [], httpx.ConnectError("aus")):
                welt.claude, welt.google, welt.ollama = claude, google, ollama
                for z in erkennung.zustaende(neu=True):
                    _sauber(z)
    assert {(r.method, r.url.path) for r in welt.anfragen} == {("GET", "/v1beta/models"), ("GET", "/api/tags")}
    assert all(c[1:] == ["auth", "status", "--json"] for c in welt.aufrufe)
    for r in welt.anfragen:
        assert not any(t in str(r.url) for t in ("generateContent", "/api/generate", "/api/chat", "/api/pull"))


def test_modul_quelle_nutzt_erkennung(welt, monkeypatch):
    """`ki_bereit` aus genut.funktionen fragt über die registrierte Quelle diese Erkennung."""
    from genut import funktionen

    monkeypatch.setattr(funktionen, "_ki_quelle", erkennung.bereit)
    assert funktionen.ki_bereit("gemini") is True
    assert funktionen.ki_bereit("openai_kompatibel") is None
