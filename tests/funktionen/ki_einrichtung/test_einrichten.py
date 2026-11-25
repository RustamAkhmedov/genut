"""Einrichten aus der Oberfläche (T017, contracts/api.md, research.md R8 bis R10).

Netz nur über `httpx.MockTransport`, Unterprozesse gefälscht, config.toml und .env in tmp_path.
Nie ein echter Installer, Download oder Prozess.
"""
from __future__ import annotations

import json
import threading
import time
import tomllib

import httpx
import pytest
from fastapi.testclient import TestClient

from genut.config import laden
from genut.funktionen.ki_einrichtung import daten, einrichten, erkennung, rechner
from genut.modelle import gemini
from genut.server import app

BASIS = "http://127.0.0.1:8765"
KOPF = {"X-Genut": "1"}
SCHLUESSEL = "AIzaGEHEIM-test-1234567890"
OLLAMA = "http://localhost:11434"
GIB = 1024 ** 3


class Netz:
    """Gefälschtes Google und Ollama. `pull` liefert die Zeilen bzw. Bytes des Downloads."""

    def __init__(self):
        self.ollama_an = True
        self.tags = [{"name": "llava:7b", "size": int(4.7 * GIB)},
                     {"name": "mistral:7b", "size": int(4.1 * GIB)}]
        self.bilder = {"llava:7b"}
        self.pull = None  # Funktion name → Iterable[bytes]
        self.show_aufrufe = []

    def __call__(self, anfrage: httpx.Request) -> httpx.Response:
        if anfrage.url.host == "generativelanguage.googleapis.com":
            schluessel = anfrage.headers.get("x-goog-api-key")
            if "offline" in schluessel:
                raise httpx.ConnectError("offline", request=anfrage)
            return httpx.Response(200 if schluessel.startswith("AIzaGEHEIM") else 400, json={"models": []})
        if not self.ollama_an:
            raise httpx.ConnectError("aus", request=anfrage)
        pfad = anfrage.url.path
        if pfad == "/api/tags":
            return httpx.Response(200, json={"models": self.tags})
        if pfad == "/api/show":
            name = json.loads(anfrage.content)["model"]
            self.show_aufrufe.append(name)
            return httpx.Response(200, json={"capabilities": ["completion", "vision"] if name in self.bilder
                                             else ["completion"]})
        if pfad == "/api/pull":
            koerper = json.loads(anfrage.content)
            assert koerper["stream"] is True
            return httpx.Response(200, content=self.pull(koerper["model"]))
        return httpx.Response(404)


def zeilen(*objekte) -> list[bytes]:
    return [json.dumps(o).encode() + b"\n" for o in objekte]


@pytest.fixture
def netz(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text('# Kommentar bleibt\n[modell]\nstandard = "gemini"\n'
                      'auswahl = ["claude_code", "gemini", "ollama"]\n', encoding="utf-8")
    monkeypatch.setenv("GENUT_CONFIG", str(config))
    monkeypatch.setattr(gemini, "WURZEL", tmp_path)  # .env in tmp_path
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    n = Netz()
    monkeypatch.setattr(erkennung, "transport", httpx.MockTransport(n))
    monkeypatch.setattr(erkennung, "ollama_programm", lambda: "/opt/ollama")

    def kein_prozess(*a, **kw):
        raise AssertionError("echter Prozess")

    monkeypatch.setattr(einrichten, "_popen", kein_prozess)
    monkeypatch.setattr(einrichten, "_schlafen", lambda s: None)
    # Claude nie echt prüfen (die echte CLI könnte installiert sein)
    monkeypatch.setitem(erkennung._PRUEFUNGEN, "claude_code",
                        lambda cfg: erkennung._zustand("claude_code", "nicht_eingerichtet", "", "einrichten"))
    monkeypatch.setattr(erkennung, "claude_befehl", lambda befehl=None: None)
    monkeypatch.setattr(rechner, "profil", lambda: daten.Rechnerprofil(
        ram_gb=16, grafik="nvidia", grafik_name="Test", grafik_gb=8, system="linux", frei_gb=100))
    laden.cache_clear()
    erkennung.leeren()
    einrichten.vergessen()
    n.config, n.env = config, tmp_path / ".env"
    yield n
    einrichten.vergessen()
    erkennung.leeren()
    laden.cache_clear()


@pytest.fixture
def c():
    return TestClient(app, base_url=BASIS, headers=KOPF)


def warten(c, kennung, frist=5.0) -> dict:
    ende = time.monotonic() + frist
    while True:
        a = c.get(f"/api/ki/auftraege/{kennung}").json()
        if a["status"] != "laeuft":
            return a
        assert time.monotonic() < ende, a
        time.sleep(0.02)


def zustand(c, name, neu=False) -> dict:
    liste = c.get(f"/api/ki/zustaende?neu={int(neu)}").json()["zustaende"]
    return next(z for z in liste if z["name"] == name)


def config_wert(netz, abschnitt, schluessel):
    return tomllib.loads(netz.config.read_text(encoding="utf-8")).get(abschnitt, {}).get(schluessel)


# ---------------------------------------------------------------- Schutz (SC-005)

SCHREIBEND = [("/api/ki/gemini/schluessel", {"schluessel": SCHLUESSEL}), ("/api/ki/claude/installieren", None),
              ("/api/ki/ollama/modell", {"name": "gemma3:4b"}), ("/api/ki/ollama/starten", None)]


@pytest.mark.parametrize("pfad,koerper", SCHREIBEND)
@pytest.mark.parametrize("kopf", [{}, {"X-Genut": "1", "Origin": "http://evil.example"},
                                  {"X-Genut": "1", "Host": "evil.example:8765"}])
def test_schreibende_routen_ohne_schutz_403(netz, pfad, koerper, kopf):
    r = TestClient(app, base_url=BASIS).post(pfad, json=koerper, headers=kopf)
    assert r.status_code == 403
    assert not netz.env.exists() and einrichten.laufend("ollama") is None


def test_alle_vertragsrouten_da():
    from genut.funktionen.ki_einrichtung.routen import router

    pfade = {(m, r.path) for r in router.routes for m in r.methods}
    assert {("POST", "/api/ki/gemini/schluessel"), ("POST", "/api/ki/claude/installieren"),
            ("GET", "/api/ki/ollama/vorschlaege"), ("POST", "/api/ki/ollama/modell"),
            ("POST", "/api/ki/ollama/starten"), ("GET", "/api/ki/auftraege/{kennung}")} <= pfade


# ---------------------------------------------------------------- Gemini


def test_gemini_gueltig_gespeichert_und_bereit(netz, c):
    r = c.post("/api/ki/gemini/schluessel", json={"schluessel": f"  {SCHLUESSEL}\n"})
    assert r.status_code == 200
    assert r.json()["name"] == "gemini" and r.json()["zustand"] == "bereit"
    assert SCHLUESSEL not in r.text
    assert f"GEMINI_API_KEY={SCHLUESSEL}" in netz.env.read_text(encoding="utf-8")
    assert gemini.schluessel() == SCHLUESSEL  # gilt im laufenden Server ohne Neustart
    z = zustand(c, "gemini")  # SC-003: nächste Abfrage ohne neu=1
    assert z["zustand"] == "bereit"


def test_gemini_ersetzt_alten_schluessel_der_umgebung(netz, c, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "alt-falsch")
    assert zustand(c, "gemini")["zustand"] == "problem"
    assert c.post("/api/ki/gemini/schluessel", json={"schluessel": SCHLUESSEL}).status_code == 200
    assert zustand(c, "gemini")["zustand"] == "bereit"


@pytest.mark.parametrize("schluessel,status,meldung", [
    ("AIzaFALSCH-123", 400, "Schlüssel wird nicht akzeptiert"),
    ("AIzaGEHEIM-offline", 503, "Keine Verbindung zu Google. Nichts gespeichert."),
    ("   ", 400, "Bitte gib einen Schlüssel ein"),
    ("A" * 201, 400, "Schlüssel wird nicht akzeptiert"),
    ('AIza"kaputt', 400, "Schlüssel wird nicht akzeptiert"),
])
def test_gemini_abgelehnt_nichts_gespeichert(netz, c, schluessel, status, meldung):
    netz.env.write_text("ANDERES=1\n", encoding="utf-8")
    r = c.post("/api/ki/gemini/schluessel", json={"schluessel": schluessel})
    assert (r.status_code, r.json()) == (status, {"detail": meldung})
    assert netz.env.read_text(encoding="utf-8") == "ANDERES=1\n"
    assert gemini.schluessel() is None


@pytest.mark.parametrize("roh", [b'{"schluessel": ["AIzaGEHEIM-test-1234567890"]}', b'["AIzaGEHEIM-test-1234567890"]',
                                 b"AIzaGEHEIM-test-1234567890", b'{"schluessel": 1}'])
def test_gemini_kaputter_body_ohne_echo(netz, c, roh):
    r = c.post("/api/ki/gemini/schluessel", content=roh, headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and SCHLUESSEL not in r.text
    assert not netz.env.exists()


# ---------------------------------------------------------------- Ollama: Vorschläge und Wahl


def test_vorschlaege_mit_vorhandenen_nur_mit_bildverstaendnis(netz, c):
    netz.tags.append({"name": "gemma3:4b", "size": int(3.3 * GIB)})
    r = c.get("/api/ki/ollama/vorschlaege")
    assert r.status_code == 200
    d = r.json()
    assert set(d) == {"profil", "vorschlaege", "vorhanden", "keins_gut"}
    assert set(d["profil"]) == {"ram_gb", "grafik", "grafik_gb", "frei_gb"}
    assert [v["name"] for v in d["vorschlaege"]] == ["gemma3:4b", "qwen3-vl:8b", "gemma3:12b"]
    assert [v["vorhanden"] for v in d["vorschlaege"]] == [True, False, False]
    assert sum(v["vorgewaehlt"] for v in d["vorschlaege"]) == 1
    assert d["vorhanden"] == [{"name": "llava:7b", "groesse_gb": 4.7}]  # mistral ohne vision, gemma3 ist Vorschlag
    assert "gemma3:4b" not in netz.show_aufrufe
    assert d["keins_gut"] is False


def test_vorschlaege_ohne_ollama_503(netz, c):
    netz.ollama_an = False
    r = c.get("/api/ki/ollama/vorschlaege")
    assert (r.status_code, r.json()) == (503, {"detail": "Ollama ist nicht erreichbar"})
    assert c.post("/api/ki/ollama/modell", json={"name": "gemma3:4b"}).status_code == 503


@pytest.mark.parametrize("name", ["mistral:7b", "gibtsnicht:1b", "", None, "x" * 201])
def test_unbekanntes_modell_400(netz, c, name):
    r = c.post("/api/ki/ollama/modell", json={"name": name})
    assert (r.status_code, r.json()) == (400, {"detail": "Unbekanntes Modell"})
    assert config_wert(netz, "ollama", "modell") is None


@pytest.mark.parametrize("name,gesetzt", [("llava:7b", "llava:7b"), ("llava", None)])
def test_vorhandenes_modell_sofort_ohne_download(netz, c, name, gesetzt):
    netz.tags.append({"name": "llava:latest", "size": GIB})
    netz.bilder.add("llava:latest")
    netz.pull = lambda n: pytest.fail("kein Download")
    r = c.post("/api/ki/ollama/modell", json={"name": name})
    assert r.status_code == 200
    assert r.json()["name"] == "ollama" and r.json()["zustand"] == "bereit" and r.json()["auftrag"] is None
    assert config_wert(netz, "ollama", "modell") == (gesetzt or "llava:latest")
    assert zustand(c, "ollama")["zustand"] == "bereit"


# ---------------------------------------------------------------- Ollama: Download


def test_download_fortschritt_steigt_und_danach_bereit(netz, c, monkeypatch):
    stufen = []
    original = einrichten._melden

    def melden(kennung, meldung=None, fortschritt=None):
        if fortschritt is not None:
            stufen.append(fortschritt)
        original(kennung, meldung, fortschritt)

    monkeypatch.setattr(einrichten, "_melden", melden)

    def pull(name):
        yield from zeilen({"status": "pulling manifest"},
                          {"status": "pulling a", "digest": "a", "total": 100, "completed": 10},
                          {"status": "pulling a", "digest": "a", "total": 100, "completed": 50})
        yield b"kein json\n"
        yield from zeilen({"status": "pulling b", "digest": "b", "total": 10, "completed": 0},  # Summe fällt
                          {"status": "pulling a", "digest": "a", "total": 100, "completed": 100},
                          {"status": "pulling b", "digest": "b", "total": 10, "completed": 10},
                          {"status": "verifying sha256 digest"}, {"status": "success"})
        netz.tags.append({"name": name, "size": 3 * GIB})

    netz.pull = pull
    assert zustand(c, "ollama")["zustand"] == "nicht_eingerichtet"  # Ergebnis liegt jetzt im Speicher
    r = c.post("/api/ki/ollama/modell", json={"name": "gemma3:4b"})
    assert r.status_code == 202 and set(r.json()) == {"auftrag"}
    a = warten(c, r.json()["auftrag"])
    assert a["status"] == "fertig" and a["fortschritt"] == 100 and a["schritt"] == "herunterladen"
    assert a["ki"] == "ollama" and a["beendet"] and a["meldung"]
    assert stufen == sorted(stufen) and stufen[-1] == 100 and len(set(stufen)) >= 3
    assert config_wert(netz, "ollama", "modell") == "gemma3:4b"
    assert config_wert(netz, "modell", "standard") == "gemini"
    assert "# Kommentar bleibt" in netz.config.read_text(encoding="utf-8")
    z = zustand(c, "ollama")  # SC-003: ohne neu=1, ohne Neustart
    assert z["zustand"] == "bereit" and z["auftrag"] is None


@pytest.mark.parametrize("art", ["abriss", "ende_ohne_success", "fehlerzeile", "http_500"])
def test_abgebrochener_download_fehler_dann_neuer_auftrag(netz, c, art):
    def kaputt(name):
        yield from zeilen({"status": "pulling a", "digest": "a", "total": 100, "completed": 30})
        if art == "abriss":
            raise httpx.ReadError("weg")
        if art == "fehlerzeile":
            yield from zeilen({"error": "max retries exceeded"})

    if art == "http_500":
        netz.pull = None
        original = netz.__call__
        netz_aufruf = lambda anfrage: (httpx.Response(500) if anfrage.url.path == "/api/pull"  # noqa: E731
                                       else original(anfrage))
        erkennung.transport = httpx.MockTransport(netz_aufruf)
    else:
        netz.pull = kaputt
    kennung = c.post("/api/ki/ollama/modell", json={"name": "qwen3-vl:8b"}).json()["auftrag"]
    a = warten(c, kennung)
    assert a["status"] == "fehler" and a["meldung"].startswith("Download abgebrochen")
    assert config_wert(netz, "ollama", "modell") is None
    if art == "fehlerzeile":
        assert "max retries exceeded" in a["meldung"]

    erkennung.transport = httpx.MockTransport(netz)
    netz.pull = lambda name: zeilen({"status": "success"})
    r = c.post("/api/ki/ollama/modell", json={"name": "qwen3-vl:8b"})
    assert r.status_code == 202
    assert warten(c, r.json()["auftrag"])["status"] == "fertig"
    assert config_wert(netz, "ollama", "modell") == "qwen3-vl:8b"


def test_zweiter_auftrag_409_und_auftrag_im_zustand_auch_bei_bereit(netz, c):
    # Lokal ist bereit (gewähltes Modell geladen) und lädt zusätzlich ein anderes Modell
    netz.tags.append({"name": "gemma3:4b", "size": 3 * GIB})
    c.post("/api/ki/ollama/modell", json={"name": "gemma3:4b"})
    weiter = threading.Event()

    def pull(name):
        yield from zeilen({"status": "pulling a", "digest": "a", "total": 100, "completed": 40})
        assert weiter.wait(5)
        yield from zeilen({"status": "success"})

    netz.pull = pull
    kennung = c.post("/api/ki/ollama/modell", json={"name": "gemma3:12b"}).json()["auftrag"]
    try:
        assert kennung.startswith("ke-") and len(kennung) == 11
        ende = time.monotonic() + 5
        while c.get(f"/api/ki/auftraege/{kennung}").json()["fortschritt"] != 40:
            assert time.monotonic() < ende
            time.sleep(0.02)
        z = zustand(c, "ollama")
        assert z["zustand"] == "bereit" and z["auftrag"] == kennung  # Dialog zeigt den laufenden Auftrag
        for pfad, koerper in [("/api/ki/ollama/modell", {"name": "qwen3-vl:8b"}), ("/api/ki/ollama/starten", None)]:
            r = c.post(pfad, json=koerper)
            assert (r.status_code, r.json()) == (409, {"detail": "Für Lokal läuft schon eine Einrichtung"})
        assert c.post("/api/ki/gemini/schluessel", json={"schluessel": SCHLUESSEL}).status_code == 200  # andere KI
    finally:
        weiter.set()
    assert warten(c, kennung)["status"] == "fertig"
    assert zustand(c, "ollama")["auftrag"] is None


def test_beendete_auftraege_10_minuten_abrufbar(netz, c, monkeypatch):
    uhr = [1000.0]
    monkeypatch.setattr(einrichten, "_uhr", lambda: uhr[0])
    netz.pull = lambda name: zeilen({"status": "success"})
    kennung = c.post("/api/ki/ollama/modell", json={"name": "gemma3:4b"}).json()["auftrag"]
    warten(c, kennung)
    uhr[0] += 599
    assert c.get(f"/api/ki/auftraege/{kennung}").status_code == 200
    uhr[0] += 2
    r = c.get(f"/api/ki/auftraege/{kennung}")
    assert (r.status_code, r.json()) == (404, {"detail": "Auftrag nicht gefunden"})
    assert c.get("/api/ki/auftraege/ke-00000000").status_code == 404


# ---------------------------------------------------------------- Ollama starten


def test_ollama_starten(netz, c, monkeypatch):
    netz.ollama_an = False
    aufrufe = []

    def popen(befehl, **kw):
        aufrufe.append((befehl, kw))
        netz.ollama_an = True

    monkeypatch.setattr(einrichten, "_popen", popen)
    assert zustand(c, "ollama")["zustand"] == "problem"
    r = c.post("/api/ki/ollama/starten")
    assert r.status_code == 202
    a = warten(c, r.json()["auftrag"])
    assert a["status"] == "fertig" and a["schritt"] == "starten" and a["fortschritt"] is None
    befehl, kw = aufrufe[0]
    assert befehl == ["/opt/ollama", "serve"] and kw["start_new_session"] is True
    assert zustand(c, "ollama")["zustand"] == "nicht_eingerichtet"  # läuft, Modell fehlt


def test_ollama_starten_antwortet_nicht(netz, c, monkeypatch):
    netz.ollama_an = False
    uhr = [0.0]
    monkeypatch.setattr(einrichten, "_popen", lambda befehl, **kw: None)
    monkeypatch.setattr(einrichten, "_uhr", lambda: uhr[0])
    monkeypatch.setattr(einrichten, "_schlafen", lambda s: uhr.__setitem__(0, uhr[0] + s))
    a = warten(c, c.post("/api/ki/ollama/starten").json()["auftrag"])
    assert a["status"] == "fehler" and a["meldung"] == "Ollama antwortet nach dem Start nicht"


def test_ollama_starten_ohne_programm_404_und_laeuft_schon_409(netz, c, monkeypatch):
    r = c.post("/api/ki/ollama/starten")
    assert (r.status_code, r.json()) == (409, {"detail": "Ollama läuft schon"})
    monkeypatch.setattr(erkennung, "ollama_programm", lambda: None)
    r = c.post("/api/ki/ollama/starten")
    assert (r.status_code, r.json()) == (404, {"detail": "Ollama ist nicht installiert"})


# ---------------------------------------------------------------- Claude


class Prozess:
    def __init__(self, zeilen, code=0, danach=None, sperre=None):
        self._zeilen, self._code, self._danach, self._sperre = zeilen, code, danach, sperre

    @property
    def stdout(self):
        for z in self._zeilen:
            yield z
        if self._sperre:
            assert self._sperre.wait(5)

    def wait(self):
        if self._danach:
            self._danach()
        return self._code

    def kill(self):
        pass


@pytest.fixture
def claude(netz, monkeypatch):
    stand = {"pfad": None, "aufrufe": []}
    monkeypatch.setattr(erkennung, "claude_befehl", lambda befehl=None: stand["pfad"])
    monkeypatch.setattr(einrichten.shutil, "which", lambda name: None)  # ~/.local/bin nicht im PATH

    def angemeldet(cfg):
        if stand["pfad"] is None:
            return erkennung._zustand("claude_code", "nicht_eingerichtet", "", "einrichten")
        return erkennung._zustand("claude_code", "problem", erkennung.NICHT_ANGEMELDET, "anmelden")

    monkeypatch.setitem(erkennung._PRUEFUNGEN, "claude_code", angemeldet)
    return stand


def test_claude_installieren(netz, c, claude, monkeypatch):
    def popen(befehl, **kw):
        claude["aufrufe"].append(befehl)
        return Prozess(["\x1b[32mLade Claude Code\x1b[0m\n", "\n", "50 %\r100 %\n", "Fertig: ~/.local/bin/claude\n"],
                       danach=lambda: claude.update(pfad="/home/x/.local/bin/claude"))

    monkeypatch.setattr(einrichten, "_popen", popen)
    assert zustand(c, "claude_code")["zustand"] == "nicht_eingerichtet"
    r = c.post("/api/ki/claude/installieren")
    assert r.status_code == 202
    a = warten(c, r.json()["auftrag"])
    assert a["status"] == "fertig" and a["schritt"] == "installieren" and a["fortschritt"] is None
    assert a["meldung"] == "Claude Code ist installiert. Melde dich jetzt im Terminal an."
    befehl = claude["aufrufe"][0]
    assert befehl[0] == "bash" and "https://claude.ai/install.sh" in befehl[-1]
    assert config_wert(netz, "claude_code", "befehl") == "/home/x/.local/bin/claude"  # Adapter findet ihn
    z = zustand(c, "claude_code")  # ohne neu=1
    assert (z["zustand"], z["aktion"]) == ("problem", "anmelden")
    r = c.post("/api/ki/claude/installieren")
    assert (r.status_code, r.json()) == (409, {"detail": "Claude Code ist schon installiert"})


def test_claude_pfad_nicht_eingetragen_wenn_befehl_gefunden(netz, c, claude, monkeypatch):
    monkeypatch.setattr(einrichten.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(einrichten, "_popen", lambda befehl, **kw: Prozess(
        ["ok\n"], danach=lambda: claude.update(pfad="/usr/bin/claude")))
    assert warten(c, c.post("/api/ki/claude/installieren").json()["auftrag"])["status"] == "fertig"
    assert config_wert(netz, "claude_code", "befehl") is None


def test_claude_installer_windows(netz, monkeypatch):
    monkeypatch.setattr(erkennung, "_windows", lambda: True)
    befehl = einrichten._installer_befehl()
    assert befehl[0] == "powershell" and befehl[-1] == "irm https://claude.ai/install.ps1 | iex"


def test_claude_installation_scheitert_dann_neuer_versuch(netz, c, claude, monkeypatch):
    monkeypatch.setattr(einrichten, "_popen", lambda befehl, **kw: Prozess(["curl: (6) Could not resolve\n"], 1))
    a = warten(c, c.post("/api/ki/claude/installieren").json()["auftrag"])
    assert a["status"] == "fehler" and a["meldung"] == "Installation fehlgeschlagen: curl: (6) Could not resolve"
    assert config_wert(netz, "claude_code", "befehl") is None
    # Exit 0, aber nichts gefunden
    monkeypatch.setattr(einrichten, "_popen", lambda befehl, **kw: Prozess([]))
    a = warten(c, c.post("/api/ki/claude/installieren").json()["auftrag"])
    assert a["status"] == "fehler" and a["meldung"] == "Claude Code wurde nach der Installation nicht gefunden"


def test_claude_zweiter_auftrag_409(netz, c, claude, monkeypatch):
    weiter = threading.Event()
    monkeypatch.setattr(einrichten, "_popen", lambda befehl, **kw: Prozess(["läuft\n"], sperre=weiter))
    kennung = c.post("/api/ki/claude/installieren").json()["auftrag"]
    try:
        r = c.post("/api/ki/claude/installieren")
        assert (r.status_code, r.json()) == (409, {"detail": "Für Claude läuft schon eine Einrichtung"})
        assert zustand(c, "claude_code")["auftrag"] == kennung
        assert c.get(f"/api/ki/auftraege/{kennung}").json()["status"] == "laeuft"
    finally:
        weiter.set()
    assert warten(c, kennung)["status"] == "fehler"  # Pfad nicht gefunden


# ---------------------------------------------------------------- kein Schlüssel nirgends (SC-005)


def test_schluessel_in_keiner_antwort_und_keinem_auftrag(netz, c):
    antworten = [c.post("/api/ki/gemini/schluessel", json={"schluessel": SCHLUESSEL}),
                 c.post("/api/ki/gemini/schluessel", json={"schluessel": SCHLUESSEL + "x"}),
                 c.get("/api/ki/zustaende?neu=1"), c.get("/api/ki/ollama/vorschlaege"), c.get("/api/ki")]
    netz.pull = lambda name: zeilen({"status": "success"})
    r = c.post("/api/ki/ollama/modell", json={"name": "gemma3:4b"})
    warten(c, r.json()["auftrag"])
    antworten += [r, c.get(f"/api/ki/auftraege/{r.json()['auftrag']}")]
    for a in antworten:
        assert SCHLUESSEL not in a.text, a.url
    with einrichten._sperre:
        assert all(SCHLUESSEL not in e.auftrag.model_dump_json() for e in einrichten._auftraege.values())


def test_meldung_saeubern():
    assert einrichten._saeubern("\x1b[1;32mgrün\x1b[0m\r\n") == "grün"
    assert einrichten._saeubern("10 %\r20 %\r") == "20 %"
    assert len(einrichten._saeubern("x" * 1000)) == einrichten.MELDUNG_MAX


# ---------------------------------------------------------------- Entwicklungsserver simuliert das Einrichten


def test_fake_server_simuliert_einrichten(tmp_path):
    import os
    import socket
    import subprocess
    import sys
    import urllib.error
    import urllib.request

    from .fake_server import WURZEL

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    config = tmp_path / "config.toml"
    config.write_text((WURZEL / "versionen" / "genut.toml").read_text(encoding="utf-8"), encoding="utf-8")
    env = {**os.environ, "GENUT_CONFIG": str(config), "GENUT_PROJEKTE": str(tmp_path / "projekte"),
           "GENUT_FAKE_KI": "claude_code:nicht_eingerichtet,gemini:nicht_eingerichtet,ollama:problem",
           "GENUT_FAKE_DAUER": "0.2"}
    p = subprocess.Popen([sys.executable, "-m", "tests.funktionen.ki_einrichtung.fake_server", str(port)],
                         cwd=WURZEL, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    basis = f"http://127.0.0.1:{port}/api/ki"

    def anfrage(pfad, koerper=None, methode=None):
        daten = json.dumps(koerper).encode() if koerper is not None else None
        req = urllib.request.Request(basis + pfad, data=daten, method=methode or ("POST" if daten else "GET"),
                                     headers={"X-Genut": "1", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def fertig(kennung):
        ende = time.monotonic() + 10
        while (a := anfrage(f"/auftraege/{kennung}")[1])["status"] == "laeuft":
            assert time.monotonic() < ende
            time.sleep(0.05)
        return a

    def zustaende():
        return {z["name"]: z for z in anfrage("/zustaende?neu=1")[1]["zustaende"]}

    try:
        ende = time.monotonic() + 30
        while True:
            try:
                anfrage("/zustaende")
                break
            except OSError:
                assert p.poll() is None and time.monotonic() < ende, "fake_server startet nicht"
                time.sleep(0.2)
        assert anfrage("/gemini/schluessel", {"schluessel": "abgelehnt-1"})[0] == 400
        assert anfrage("/gemini/schluessel", {"schluessel": "offline-1"})[0] == 503
        assert anfrage("/gemini/schluessel", {"schluessel": "gut-1"})[1]["zustand"] == "bereit"
        assert not (WURZEL / ".env").exists() or "gut-1" not in (WURZEL / ".env").read_text(encoding="utf-8")

        status, d = anfrage("/claude/installieren", methode="POST")
        assert status == 202 and anfrage("/claude/installieren", methode="POST")[0] == 409
        assert fertig(d["auftrag"])["status"] == "fertig"
        assert zustaende()["claude_code"]["aktion"] == "anmelden"

        assert anfrage("/ollama/vorschlaege")[0] == 503
        assert fertig(anfrage("/ollama/starten", methode="POST")[1]["auftrag"])["status"] == "fertig"
        assert zustaende()["ollama"]["ursache"] == "kein Modell gewählt"
        status, d = anfrage("/ollama/vorschlaege")
        assert status == 200 and d["vorhanden"] == [{"name": "llava:7b", "groesse_gb": 4.4}]
        kennung = anfrage("/ollama/modell", {"name": "qwen3-vl:8b"})[1]["auftrag"]
        assert zustaende()["ollama"]["auftrag"] == kennung
        assert fertig(kennung)["fortschritt"] == 100
        assert zustaende()["ollama"]["zustand"] == "bereit"
        assert 'modell = "qwen3-vl:8b"' in config.read_text(encoding="utf-8")
    finally:
        p.terminate()
        p.wait(10)
