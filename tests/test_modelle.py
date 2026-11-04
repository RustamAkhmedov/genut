"""Adapter ohne echte Dienste: Anfrageformat und Antwort-Auswertung mit gemocktem httpx/subprocess."""
import json
import subprocess

import httpx
import pytest

from genut.modelle.base import ModellFehler, json_aus_text
from genut.modelle.claude_code import ClaudeCode
from genut.modelle.ollama import Ollama
from tests.conftest import FIX

FOTO = FIX / "fotos" / "001.jpg"


class Antwort:
    def __init__(self, status, daten):
        self.status_code, self._d = status, daten
        self.text = json.dumps(daten)

    def json(self):
        return self._d


def test_json_aus_text():
    assert json_aus_text('Hier:\n```json\n{"a": 1}\n```') == {"a": 1}
    assert json_aus_text('bla {"a": {"b": 2}} bla') == {"a": {"b": 2}}
    with pytest.raises(ModellFehler):
        json_aus_text("kein json")


def test_ollama_anfrage(monkeypatch):
    gesendet = {}

    def post(url, json, timeout):
        gesendet.update(url=url, body=json)
        return Antwort(200, {"message": {"content": '{"x": 1}'}})

    monkeypatch.setattr(httpx, "post", post)
    o = Ollama({"url": "http://h:1", "modell": "m"})
    assert o.json("{{bild_hinweis}}\nAufgabe", {"type": "object"}, [FOTO]) == {"x": 1}
    msg = gesendet["body"]["messages"][0]
    assert gesendet["url"] == "http://h:1/api/chat" and gesendet["body"]["format"] == {"type": "object"}
    assert len(msg["images"]) == 1 and "001.jpg" in msg["content"] and "{{" not in msg["content"]


def test_claude_code_aufruf(monkeypatch):
    gesehen = {}

    def run(cmd, capture_output, text, timeout, cwd):
        gesehen["cmd"] = cmd
        out = {"is_error": False, "result": '{"a":1}', "structured_output": {"a": 1}}
        return subprocess.CompletedProcess(cmd, 0, json.dumps(out), "")

    monkeypatch.setattr(subprocess, "run", run)
    c = ClaudeCode({"befehl": "claude"})
    assert c.json("{{bild_hinweis}}\nX", {"type": "object"}, [FOTO]) == {"a": 1}
    cmd = gesehen["cmd"]
    assert cmd[cmd.index("--allowedTools") + 1] == "Read"
    assert "Bash" in cmd[cmd.index("--disallowedTools") + 1]
    assert str(FOTO.resolve()) in cmd[2] and "--json-schema" in cmd


def test_claude_code_fehler(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(
        cmd, 1, json.dumps({"is_error": True, "result": "Limit erreicht"}), ""))
    with pytest.raises(ModellFehler, match="Limit"):
        ClaudeCode({}).text("x", [])


def test_gemini_anfrage_modellwahl_und_retry(monkeypatch):
    from genut.modelle import gemini as gm
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(gm.time, "sleep", lambda s: None)
    aufrufe = []

    def get(url, params, headers, timeout):
        class R(Antwort):
            def raise_for_status(self):
                pass
        return R(200, {"models": [
            {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.6-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.9-flash-lite", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.8-pro", "supportedGenerationMethods": ["generateContent"]}]})

    def post(url, json, headers, timeout):
        aufrufe.append((url, json, headers))
        if len(aufrufe) == 1:
            return Antwort(429, {"error": {"details": [{"retryDelay": "3s"}]}})
        return Antwort(200, {"candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"text": "nachdenken", "thought": True}, {"text": '{"ok": 1}'}]}}]})

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(httpx, "post", post)
    g = gm.Gemini({"modell": ""})
    assert g.json("{{bild_hinweis}}\nAufgabe", {"type": "object"}, [FOTO]) == {"ok": 1}
    url, body, headers = aufrufe[-1]
    assert len(aufrufe) == 2 and url.endswith("/models/gemini-3.8-flash:generateContent")
    assert g._kandidaten() == ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.9-flash-lite"]  # lite zuletzt, 2.x/pro nie
    assert headers["x-goog-api-key"] == "test"
    teile = body["contents"][0]["parts"]
    assert "001.jpg" in teile[0]["text"] and teile[1]["inline_data"]["mime_type"] == "image/jpeg"
    assert body["generationConfig"]["responseJsonSchema"] == {"type": "object"}


def test_gemini_ohne_schluessel(monkeypatch, tmp_path):
    from genut.modelle import gemini as gm
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(gm, "WURZEL", tmp_path)
    with pytest.raises(ModellFehler, match="aistudio"):
        gm.Gemini({"modell": "x"}).text("hallo", [])
    (tmp_path / ".env").write_text("# Kommentar\nGEMINI_API_KEY=abc123\n")
    assert gm.schluessel() == "abc123"


def test_gemini_weicht_bei_ueberlastung_aus(monkeypatch):
    from genut.modelle import gemini as gm
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(gm.time, "sleep", lambda s: None)
    urls = []

    def post(url, json, headers, timeout):
        urls.append(url)
        if "3.8" in url:
            return Antwort(503, {"error": {"status": "UNAVAILABLE"}})
        return Antwort(200, {"candidates": [{"content": {"parts": [{"text": "OK"}]}}]})

    monkeypatch.setattr(httpx, "post", post)
    g = gm.Gemini({"modell": ""})
    g._liste = ["gemini-3.8-flash", "gemini-3.7-flash"]
    assert g.text("x", []) == "OK" and "3.7" in urls[-1] and len(urls) == 3
    assert g.text("y", []) == "OK" and "3.7" in urls[-1]   # bleibt beim funktionierenden Modell


def test_gemini_zu_komplexes_schema_und_tageslimit(monkeypatch):
    from genut.modelle import gemini as gm
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(gm.time, "sleep", lambda s: None)
    monkeypatch.setattr(gm, "_ZU_KOMPLEX", set())
    aufrufe = []

    def post(url, json, headers, timeout):
        aufrufe.append((url, json))
        if "3.8" in url:
            return Antwort(429, {"error": {"details": [{"violations": [
                {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}, {"retryDelay": "4000s"}]}})
        if "responseJsonSchema" in json["generationConfig"]:
            return Antwort(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT"}})
        return Antwort(200, {"candidates": [{"content": {"parts": [{"text": '{"a": 1}'}]}}]})

    monkeypatch.setattr(httpx, "post", post)
    g = gm.Gemini({"modell": ""})
    g._liste = ["gemini-3.8-flash", "gemini-3.7-flash"]
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}}
    assert g.json("x", schema, []) == {"a": 1}
    url, body = aufrufe[-1]
    assert "3.7" in url and '"properties"' in body["contents"][0]["parts"][0]["text"]
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    n = len(aufrufe)
    assert g.json("y", schema, []) == {"a": 1} and len(aufrufe) == n + 1   # gemerkt: kein 400-Versuch mehr


def test_ki_schalter_api(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from genut.config import laden
    from genut.server import app
    cfg = tmp_path / "config.toml"
    cfg.write_text('[server]\nport = 8765\n\n[modell]\nstandard = "claude_code"   # Kommentar bleibt\n\n[ollama]\nmodell = "x"\n')
    monkeypatch.setenv("GENUT_CONFIG", str(cfg))
    laden.cache_clear()
    try:
        c = TestClient(app)
        assert c.get("/api/ki").json()["standard"] == "claude_code"
        r = c.put("/api/ki", json={"standard": "gemini"})
        assert r.status_code == 200 and r.json()["standard"] == "gemini"
        text = cfg.read_text()
        assert 'standard = "gemini"   # Kommentar bleibt' in text and 'modell = "x"' in text
        assert c.put("/api/ki", json={"standard": "quatsch"}).status_code == 400
    finally:
        laden.cache_clear()
