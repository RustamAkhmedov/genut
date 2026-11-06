"""Adapter für die Google-Gemini-API (generateContent mit JSON-Schema).

Schlüssel: Umgebungsvariable GEMINI_API_KEY oder Zeile `GEMINI_API_KEY=…` in `.env` im Projektordner
(gratis unter https://aistudio.google.com/apikey). Modell: config.toml [gemini] modell; leer = das neueste
„flash“-Modell, das die API für generateContent anbietet.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import time
from pathlib import Path

import httpx

from ..config import WURZEL
from .base import ModellFehler, anhang_hinweis, b64, bild_hinweis_einsetzen, json_aus_text

TIMEOUT = 600
BASIS = "https://generativelanguage.googleapis.com/v1beta"
VERSUCHE = 5          # bei 429/5xx (Gratis-Kontingent: wenige Anfragen pro Minute)
# Schemas, die Gemini als zu komplex ablehnt (400 INVALID_ARGUMENT) – dann JSON-Modus + Schema im Prompt
_ZU_KOMPLEX: set[str] = set()


def schluessel() -> str | None:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key:
        return key.strip()
    env = WURZEL / ".env"
    if env.exists():
        for zeile in env.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*(?:export\s+)?(GEMINI_API_KEY|GOOGLE_API_KEY)\s*=\s*['\"]?([^'\"\s#]+)", zeile)
            if m:
                return m.group(2)
    return None


def _version(name: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", name.split("/")[-1])[:3])


def _konfig(modell: str, basis: dict) -> dict:
    """Ab Gemini 3 bleibt die Temperatur beim Standard 1.0: Google warnt, dass niedrigere Werte zu Schleifen und
    schlechteren Antworten führen können (Gemini-3-Prompting-Guide). Nur ältere Modelle (2.x) bekommen 0.2;
    Namen ohne Version (z. B. gemini-flash-latest) zeigen auf aktuelle Modelle und bleiben beim Standard."""
    v = _version(modell)
    return {**basis, "temperature": 0.2} if v and v[0] < 3 else basis


class Gemini:
    name = "gemini"
    bbox_format = "box_2d"   # Gemini ist auf [ymin, xmin, ymax, xmax] 0–1000 trainiert
    beispiele = True         # Beispiel-Patch im Prompt (pipeline.beispiel_text)

    def __init__(self, cfg: dict):
        self.modell = (cfg.get("modell") or "").strip()
        self.basis = (cfg.get("basis_url") or BASIS).rstrip("/")
        self.gruende: dict[str, int] = {}   # Modell → letzter HTTP-Fehler (für verständliche Meldungen)

    def _key(self) -> str:
        key = schluessel()
        if not key:
            raise ModellFehler("Kein Gemini-Schlüssel: GEMINI_API_KEY in .env oder als Umgebungsvariable setzen "
                               "(gratis unter https://aistudio.google.com/apikey)")
        return key

    def _kandidaten(self) -> list[str]:
        """Konfiguriertes Modell, sonst alle gemini-x.y-flash, neueste zuerst (Ausweichen bei Überlastung)."""
        if self.modell:
            return [self.modell]
        if getattr(self, "_liste", None):
            return self._liste
        try:
            r = httpx.get(f"{self.basis}/models", params={"pageSize": 200}, headers={"x-goog-api-key": self._key()},
                          timeout=30)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ModellFehler(f"Gemini-Modellliste nicht abrufbar: {e}") from e
        namen = [m["name"].split("/")[-1] for m in r.json().get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])
                 and re.search(r"gemini-[\d.]+-flash(-preview|-lite)?$", m["name"])
                 and not re.search(r"gemini-2\.", m["name"])]   # 2.x ist für neue Nutzer abgeschaltet
        if not namen:
            raise ModellFehler("Kein passendes Gemini-Flash-Modell gefunden – in config.toml [gemini] modell eintragen")
        # erst alle normalen Flash-Modelle (neueste zuerst), dann die schwächeren „lite“ als letzte Reserve
        self._liste = sorted(namen, key=lambda n: ("lite" not in n, _version(n), "preview" not in n), reverse=True)
        return self._liste

    def _modell(self) -> str:
        return self._kandidaten()[getattr(self, "_nr", 0)]

    def info(self) -> dict:
        """Für die Logs: welches Modell zuletzt geantwortet hat und welche Modelle mit welchem HTTP-Fehler ausgefallen
        sind. Ohne Netzwerkzugriff (nur bereits bekannte Werte)."""
        liste = [self.modell] if self.modell else (getattr(self, "_liste", None) or [])
        nr = getattr(self, "_nr", 0)
        return {"modell": liste[nr] if nr < len(liste) else None, "fehler": dict(self.gruende)}

    def _aufruf(self, prompt: str, bilder: list[Path], schema: dict | None, schema_im_prompt: bool = False) -> str:
        teile: list[dict] = [{"text": bild_hinweis_einsetzen(prompt, anhang_hinweis(bilder))}]
        for b in bilder:
            mime = mimetypes.guess_type(b.name)[0] or "image/jpeg"
            teile.append({"inline_data": {"mime_type": mime, "data": b64(b)}})
        konfig: dict = {}
        if schema is not None:
            konfig["responseMimeType"] = "application/json"
            if not schema_im_prompt:
                konfig["responseJsonSchema"] = schema
        warten = 10.0
        ueberlastet = 0
        for versuch in range(VERSUCHE * 2):
            url = f"{self.basis}/models/{self._modell()}:generateContent"
            body = {"contents": [{"role": "user", "parts": teile}], "generationConfig": _konfig(self._modell(), konfig)}
            try:
                r = httpx.post(url, json=body, headers={"x-goog-api-key": self._key()}, timeout=TIMEOUT)
            except httpx.HTTPError as e:
                if versuch == VERSUCHE * 2 - 1:
                    raise ModellFehler(f"Gemini nicht erreichbar: {e}") from e
                time.sleep(warten); warten = min(warten * 2, 120)
                continue
            if r.status_code >= 400:
                self.gruende[self._modell()] = r.status_code
            if r.status_code in (500, 502, 503, 504):
                ueberlastet += 1
                # überlastet: nach 2 Versuchen aufs nächstältere Flash-Modell ausweichen (falls vorhanden)
                if ueberlastet >= 2 and getattr(self, "_nr", 0) + 1 < len(self._kandidaten()):
                    self._nr = getattr(self, "_nr", 0) + 1
                    ueberlastet = 0
                    continue
                if versuch < VERSUCHE * 2 - 1:
                    time.sleep(5)
                    continue
            if r.status_code == 404 and getattr(self, "_nr", 0) + 1 < len(self._kandidaten()):
                self._nr = getattr(self, "_nr", 0) + 1   # Modell für neue Nutzer abgeschaltet → nächstes
                continue
            if r.status_code == 429 and "PerDay" in r.text and getattr(self, "_nr", 0) + 1 < len(self._kandidaten()):
                self._nr = getattr(self, "_nr", 0) + 1   # Tageslimit dieses Modells erreicht → nächstes Modell
                continue
            if r.status_code == 429 and versuch < VERSUCHE * 2 - 1:
                m = re.search(r'"retryDelay":\s*"(\d+)', r.text)
                time.sleep(max(warten, float(m.group(1)) + 1) if m else warten)
                warten = min(warten * 2, 120)
                continue
            break
        if r.status_code == 429 and "PerDay" in r.text:
            raise ModellFehler("Gemini: Tageslimit des Gratis-Kontingents bei allen Flash-Modellen erreicht – "
                               "morgen wieder oder in der Kopfzeile auf Claude umschalten")
        if r.status_code >= 500:
            raise ModellFehler("Gemini ist gerade überlastet (alle Flash-Modelle) – in ein paar Minuten nochmal "
                               f"versuchen oder auf Claude umschalten. HTTP {r.status_code}")
        if r.status_code >= 400:
            raise ModellFehler(f"Gemini HTTP {r.status_code} (Modelle: {self.gruende}): {r.text[:600]}")
        daten = r.json()
        try:
            kandidat = daten["candidates"][0]
            text = "".join(t.get("text", "") for t in kandidat["content"]["parts"] if not t.get("thought"))
        except (KeyError, IndexError) as e:
            grund = daten.get("promptFeedback") or daten.get("candidates", [{}])[0].get("finishReason")
            raise ModellFehler(f"Gemini lieferte keinen Text ({grund}): {json.dumps(daten)[:400]}") from e
        if kandidat.get("finishReason") == "MAX_TOKENS":
            raise ModellFehler("Gemini-Antwort abgeschnitten (MAX_TOKENS) – weniger Themen auf einmal generieren")
        return text

    def text(self, prompt: str, bilder: list[Path]) -> str:
        return self._aufruf(prompt, bilder, None).strip()

    def json(self, prompt: str, schema: dict, bilder: list[Path]) -> dict:
        roh = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        if roh not in _ZU_KOMPLEX:
            try:
                return json_aus_text(self._aufruf(prompt, bilder, schema))
            except ModellFehler as e:
                if "HTTP 400" not in str(e) or "INVALID_ARGUMENT" not in str(e):
                    raise
                _ZU_KOMPLEX.add(roh)   # Gemini-Grenze für Schema-Komplexität (viele Blocktypen)
        p = (prompt + "\n\n## Antwortformat\n\nAntworte ausschließlich mit einem JSON-Objekt, das genau diesem "
             "JSON-Schema entspricht (Felder, Pflichtfelder, erlaubte Werte bei `const`/`enum`):\n\n" + roh)
        return json_aus_text(self._aufruf(p, bilder, schema, schema_im_prompt=True))
