"""Handprobe ohne echte KI (quickstart.md Schritt 2): startet die App mit dem Fake-Prüfer aus fake.py.

    GENUT_PROJEKTE=/tmp/pr-projekte .venv/bin/python -m tests.funktionen.pruefung.fake_server [PORT]

Port: Argument, sonst GENUT_PORT, sonst 8766. Projekte aus GENUT_PROJEKTE (Standard wie die App). Die Funktion
`pruefung` wird für diesen Prozess über eine temporäre Konfiguration (GENUT_CONFIG) eingeschaltet; eine
vorhandene config.toml wird dafür mit `pruefung = true` übernommen, die Datei selbst bleibt unverändert.
Der Fake-Prüfer stellt feste Fragen je Thema und fragt bei Antworten unter 40 Zeichen einmal nach.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def _konfiguration() -> str:
    from genut.config import config_pfad

    vorhanden = config_pfad()
    text = vorhanden.read_text(encoding="utf-8") if vorhanden.exists() else ""
    ordner = Path(tempfile.mkdtemp(prefix="genut-fake-"))
    pfad = ordner / "config.toml"
    # Spätere Wiederholung eines Abschnitts wäre ungültiges TOML; daher ein Punkt-Schlüssel nur, wenn es
    # keinen [funktionen]-Abschnitt gibt, sonst den Schlüssel dort ersetzen/ergänzen.
    zeilen = text.splitlines()
    if "[funktionen]" in (z.strip() for z in zeilen):
        neu, drin, gesetzt = [], False, False
        for z in zeilen:
            s = z.strip()
            if s.startswith("["):
                if drin and not gesetzt:
                    neu.append("pruefung = true")
                    gesetzt = True
                drin = s == "[funktionen]"
            if drin and s.replace(" ", "").startswith("pruefung="):
                z, gesetzt = "pruefung = true", True
            neu.append(z)
            if drin and s == "[funktionen]":
                pass
        if drin and not gesetzt:
            neu.append("pruefung = true")
        text = "\n".join(neu) + "\n"
    else:
        text += "\n[funktionen]\npruefung = true\n"
    # keine echte KI-Erkennung in der Handprobe und in den Browser-Tests (Constitution VII)
    text = "\n".join(z for z in text.splitlines() if not z.strip().startswith("ki_einrichtung"))
    text = "\n".join("[funktionen]\nki_einrichtung = false" if z.strip() == "[funktionen]" else z
                     for z in text.splitlines()) + "\n"
    pfad.write_text(text, encoding="utf-8")
    return str(pfad)


def main() -> None:
    os.environ["GENUT_CONFIG"] = _konfiguration()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("GENUT_PORT", "8766"))

    from genut.funktionen.pruefung import logik

    from .fake import FakeModell

    fake = FakeModell()
    logik.waehlen = lambda name: fake  # derselbe Standard-Prüfer wie in den Tests

    import uvicorn

    from genut.server import app

    print(f"Fake-Prüfer: http://127.0.0.1:{port}  (Projekte: {os.environ.get('GENUT_PROJEKTE', 'Standard')})", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
