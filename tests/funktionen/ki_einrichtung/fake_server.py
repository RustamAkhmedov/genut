"""Entwicklungsserver ohne echte KI: dieselbe App, die KI-Zustände kommen aus GENUT_FAKE_KI.

    GENUT_FAKE_KI=claude_code:bereit,gemini:problem,ollama:nicht_eingerichtet \\
    GENUT_PROJEKTE=/tmp/ki-projekte .venv/bin/python -m tests.funktionen.ki_einrichtung.fake_server [PORT]

Zustände: bereit, nicht_eingerichtet, problem. Nicht genannte KIs sind nicht_eingerichtet.
Zusätzlich `ollama:ohne_modell`: Ollama läuft, aber kein Modell ist gewählt (Dialog mit Vorschlägen).
Port: Argument, sonst GENUT_PORT, sonst 8767. Ohne GENUT_CONFIG gilt eine temporäre Kopie von
versionen/genut.toml (drei KIs), eine vorhandene config.toml bleibt also unverändert.
Es wird weder eine CLI aufgerufen noch eine KI übers Netz angefragt; Aufträge, die ein Modell bräuchten, scheitern.

Einrichten wird nur simuliert (nie ein echter Installer, Download oder Prozess, nie die echte `.env`):
- Gemini: ein Schlüssel mit „abgelehnt“ wird abgelehnt, mit „offline“ gibt es keine Verbindung, sonst ok.
- Claude installieren: einige Ausgabezeilen, danach „problem“ (nicht angemeldet).
- Lokal: Ollama starten → `ohne_modell`; Modell laden → Fortschritt bis 100, danach „bereit“. Geladen ist
  ein fremdes Modell `llava:7b` mit Bildverständnis (erscheint unter „vorhanden“). Auch das Wählen eines schon geladenen Modells macht Lokal „bereit“.
- GENUT_FAKE_DAUER: Sekunden je Auftrag (Standard 2). GENUT_FAKE_EINRICHTEN=fehler: jeder Auftrag scheitert,
  fehler_einmal: nur der erste (für „Nochmal versuchen“).
- GENUT_FAKE_RECHNER=schwach: Rechner ohne Grafikkarte mit 4 GB (kein Vorschlag „gut“), sonst ein fester
  Rechner mit 16 GB und 8 GB Grafikspeicher.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[3]
ZUSTAENDE = ("bereit", "nicht_eingerichtet", "problem")
# zusätzliche Fälle einzelner KIs: Name → Fall → (Zustand, Ursache, Aktion)
SONDERFAELLE = {"ollama": {"ohne_modell": ("nicht_eingerichtet", "kein Modell gewählt", "einrichten")}}
FREMDES_MODELL = "llava:7b"
# KI → Zustand → (Ursache, Aktion), wie sie die echte Erkennung liefern kann
FAELLE = {
    "claude_code": {"nicht_eingerichtet": ("", "einrichten"), "problem": ("nicht angemeldet", "anmelden")},
    "gemini": {"nicht_eingerichtet": ("", "schluessel"),
               "problem": ("Schlüssel wird nicht akzeptiert", "schluessel")},
    "ollama": {"nicht_eingerichtet": ("", "einrichten"), "problem": ("Ollama läuft nicht", "starten")},
}


def fake_zustaende(text: str) -> dict[str, str]:
    """Liest `name:zustand,…`; wirft ValueError bei unbekannten Namen oder Zuständen."""
    ergebnis = dict.fromkeys(FAELLE, "nicht_eingerichtet")
    for teil in filter(None, (t.strip() for t in text.split(","))):
        name, _, zustand = teil.partition(":")
        if name not in FAELLE or (zustand not in ZUSTAENDE and zustand not in SONDERFAELLE.get(name, {})):
            raise ValueError(f"GENUT_FAKE_KI: ungültiger Eintrag {teil!r}")
        ergebnis[name] = zustand
    return ergebnis


def _ohne_modell(name: str):
    from genut.modelle.base import ModellFehler

    raise ModellFehler("Entwicklungsserver: es wird keine KI aufgerufen")


def einrichten() -> None:
    """Ersetzt die Prüfungen der Erkennung (Speicher, `bereit` und Routen bleiben echt) und sperrt Modelle."""
    from genut import pipeline, server
    from genut.funktionen.ki_einrichtung import erkennung

    gewuenscht = fake_zustaende(os.environ.get("GENUT_FAKE_KI", ""))

    def pruefung(name: str):
        # liest den Stand bei jeder Prüfung: simuliertes Einrichten ändert ihn
        def lauf(cfg):
            fall = gewuenscht[name]
            if fall in SONDERFAELLE.get(name, {}):
                return erkennung._zustand(name, *SONDERFAELLE[name][fall])
            return erkennung._zustand(name, fall, *FAELLE[name].get(fall, ("", "")))
        return lauf

    erkennung._PRUEFUNGEN.update({name: pruefung(name) for name in FAELLE})
    einrichten_simulieren(gewuenscht)
    erkennung.leeren()
    pipeline.waehlen = server.waehlen = _ohne_modell
    try:
        from genut.funktionen.pruefung import logik
    except ImportError:  # Modul gelöscht
        pass
    else:
        logik.waehlen = _ohne_modell


def einrichten_simulieren(gewuenscht: dict[str, str]) -> None:
    """Ersetzt alles, was beim Einrichten nach außen ginge, durch eine Simulation auf `gewuenscht`."""
    import httpx

    from genut.funktionen.ki_einrichtung import daten, einrichten, env, erkennung, rechner

    dauer = float(os.environ.get("GENUT_FAKE_DAUER", "2"))
    fehlerart = os.environ.get("GENUT_FAKE_EINRICHTEN")
    fehlschlaege = {"fehler": float("inf"), "fehler_einmal": 1}.get(fehlerart, 0)  # so viele Aufträge scheitern noch
    geladene: set[str] = set()  # Modelle, die in diesem Lauf eingestellt wurden
    echtes_modell_setzen = einrichten._modell_setzen

    def kein_prozess(*args, **kw):
        raise RuntimeError("Entwicklungsserver: es wird kein Prozess gestartet")

    # Sicherung: kein Netz, kein Unterprozess, auch wenn eine Stelle unten vergessen wäre
    erkennung.transport = httpx.MockTransport(lambda anfrage: httpx.Response(503))
    einrichten._popen = kein_prozess

    def schritte(melden, texte: list[str], mit_prozent: bool) -> None:
        for i, text in enumerate(texte, 1):
            time.sleep(dauer / len(texte))
            melden(text, round(i * 100 / len(texte)) if mit_prozent else None)
        nonlocal fehlschlaege
        if fehlschlaege:
            fehlschlaege -= 1
            raise einrichten.AuftragFehler("Simulierter Fehler")

    def claude_installieren(melden):
        schritte(melden, ["Lade Claude Code …", "Installiere nach ~/.local/bin …", "Fertig."], False)
        gewuenscht["claude_code"] = "problem"
        return "Claude Code ist installiert. Melde dich jetzt im Terminal an."

    def laden(url, name, melden):
        schritte(melden, [f"Lade {name} herunter …"] * 5, True)
        einrichten._modell_setzen(name)
        return f"{name} ist geladen und eingestellt"

    def modell_setzen(name):  # wie echt: config schreiben; danach findet die Erkennung das Modell
        echtes_modell_setzen(name)
        if name != FREMDES_MODELL:
            geladene.add(name)
        gewuenscht["ollama"] = "bereit"

    def ollama_starten(programm, url, melden):
        schritte(melden, ["Starte Ollama …"], False)
        gewuenscht["ollama"] = "ohne_modell"
        return "Ollama läuft"

    def gemini_pruefen(schluessel, basis=None):
        return "abgelehnt" if "abgelehnt" in schluessel else "keine_verbindung" if "offline" in schluessel else "ok"

    def schluessel_speichern(schluessel):  # nie die echte .env
        gewuenscht["gemini"] = "bereit"

    def ollama_modelle(url=None):
        if gewuenscht["ollama"] not in ("bereit", "ohne_modell"):
            return None
        tags = [{"name": FREMDES_MODELL, "size": 4_700_000_000}]
        namen = set(geladene)
        if gewuenscht["ollama"] == "bereit" and not namen:
            namen.add(daten.modelle_laden()[0].name)
        tags += [{"name": n, "size": 3_300_000_000} for n in sorted(namen)]
        return tags

    def profil():
        if os.environ.get("GENUT_FAKE_RECHNER") == "schwach":
            return daten.Rechnerprofil(ram_gb=4, grafik="keine", system="linux", frei_gb=50)
        return daten.Rechnerprofil(ram_gb=16, grafik="nvidia", grafik_name="Fake", grafik_gb=8,
                                   system="linux", frei_gb=50)

    einrichten._claude_installieren = claude_installieren
    einrichten._laden = laden
    einrichten._modell_setzen = modell_setzen
    einrichten._ollama_starten = ollama_starten
    einrichten.versteht_bilder = lambda url, name: name == FREMDES_MODELL
    erkennung.gemini_schluessel_pruefen = gemini_pruefen
    erkennung.claude_befehl = lambda befehl=None: (
        None if gewuenscht["claude_code"] == "nicht_eingerichtet" else "/fake/claude")
    erkennung.ollama_programm = lambda: None if gewuenscht["ollama"] == "nicht_eingerichtet" else "/fake/ollama"
    erkennung.ollama_modelle = ollama_modelle
    env.schluessel_speichern = schluessel_speichern
    rechner.profil = profil


def main() -> None:
    if not os.environ.get("GENUT_CONFIG"):
        kopie = Path(tempfile.mkdtemp(prefix="genut-fake-ki-")) / "config.toml"
        shutil.copy(WURZEL / "versionen" / "genut.toml", kopie)
        os.environ["GENUT_CONFIG"] = str(kopie)
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("GENUT_PORT", "8767"))
    einrichten()

    import uvicorn

    from genut.server import app

    print(f"Fake-KIs: http://127.0.0.1:{port}  (Projekte: {os.environ.get('GENUT_PROJEKTE', 'Standard')})", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
