"""Unterbefehle `python -m genut ki …` (specs/005b-ein-genut/contracts/cli.md).

Die Setup-Skripte werten Exit-Codes und die `--json`-Ausgabe aus (ein JSON-Objekt auf stdout, nur ASCII,
damit auch Windows-Pipes nichts verfälschen). Kein Text nennt den Schlüssel.
"""
from __future__ import annotations

import argparse
import json
import sys

from ...config import auswahl_ergaenzen, laden, wert_setzen
from . import daten, env, erkennung, modellwahl, rechner

REIHENFOLGE = erkennung.GEPRUEFT  # Claude → Gemini → Lokal
SETZBAR = ("modell.standard", "ollama.modell", "ollama.url", "claude_code.befehl")
_TITEL = {"claude_code": "Claude", "gemini": "Gemini", "ollama": "Lokal"}
_ZUSTAND = {"bereit": "bereit", "nicht_eingerichtet": "nicht eingerichtet", "problem": "Problem"}


def _ausgeben(objekt: dict) -> None:
    print(json.dumps(objekt))


def _zeile(z: daten.KiZustand) -> str:
    return f"{_TITEL[z.name]}: {_ZUSTAND[z.zustand]}" + (f" ({z.ursache})" if z.ursache else "")


def _zustand(args) -> None:
    if args.name is None:
        liste = erkennung.zustaende(neu=True)
        if args.json:
            _ausgeben({"zustaende": [z.model_dump(mode="json") for z in liste],
                       "keine_bereit": not any(z.zustand == "bereit" for z in liste)})
        else:
            for z in liste:
                print(_zeile(z))
        return
    z = erkennung.zustand(args.name, neu=True)
    if args.json:
        objekt = z.model_dump(mode="json")
        # voller Pfad: das Setup trägt ihn ein, wenn `claude` nicht im PATH liegt
        if z.name == "claude_code" and z.zustand != "nicht_eingerichtet" and (pfad := erkennung.claude_befehl()):
            objekt["befehl"] = pfad
        _ausgeben(objekt)
    else:
        print(_zeile(z))
    if z.zustand != "bereit":
        sys.exit(1)


def _modelle(args) -> None:
    profil = rechner.profil()
    tags = erkennung.ollama_modelle() or []  # leer auch ohne laufendes Ollama
    geladen = [m.name for m in daten.modelle_laden() if erkennung.ollama_hat_modell(tags, m.name)]
    liste = modellwahl.vorschlaege(profil, geladen)
    keins_gut = modellwahl.keins_gut(liste)
    if args.json:
        _ausgeben({"profil": profil.model_dump(include={"ram_gb", "grafik", "grafik_gb", "frei_gb"}),
                   "vorschlaege": [v.model_dump() for v in liste],
                   "vorhanden": [],  # eigene Modelle mit Bildverständnis zeigt nur das Tool
                   "keins_gut": keins_gut})
        return
    for v in liste:
        zusatz = "".join((" [Vorwahl]" if v.vorgewaehlt else "", " [schon geladen]" if v.vorhanden else ""))
        print(f"{v.name} ({v.download_gb:g} GB){zusatz}: {v.begruendung}")
        if v.platz_warnung and not v.vorhanden:
            print("  Achtung: Der freie Speicherplatz reicht vielleicht nicht.")
    if keins_gut:
        print("Kein lokales Modell läuft auf diesem Rechner gut, Gemini wird empfohlen.")


def _stdin_lesen() -> str:
    roh = getattr(sys.stdin, "buffer", None)
    text = roh.read().decode("utf-8", "replace") if roh else sys.stdin.read()
    return text.replace("﻿", "").strip()  # PowerShell stellt gern ein BOM voran


def _gemini_pruefen(args) -> None:
    schluessel = _stdin_lesen()
    if not env.schluessel_gueltig(schluessel):
        ergebnis = "abgelehnt"
    else:
        ergebnis = erkennung.gemini_schluessel_pruefen(schluessel, laden().get("gemini", {}).get("basis_url"))
    if ergebnis == "ok":
        env.schluessel_speichern(schluessel)
        print("Schlüssel funktioniert und ist in .env gespeichert (nur auf diesem Computer).")
    elif ergebnis == "abgelehnt":
        print("Schlüssel wird nicht akzeptiert. Nichts gespeichert.")
        sys.exit(1)
    else:
        print("Keine Verbindung zu Google. Nichts gespeichert.")
        sys.exit(3)


def _abbruch(meldung: str, code: int) -> None:
    print(meldung, file=sys.stderr)
    sys.exit(code)


def _setzen(args) -> None:
    if args.schluessel not in SETZBAR:
        _abbruch(f"Unbekannter Schlüssel. Erlaubt: {', '.join(SETZBAR)}", 2)
    if args.schluessel == "modell.standard" and args.wert not in REIHENFOLGE:
        _abbruch(f"modell.standard muss eines davon sein: {', '.join(REIHENFOLGE)}", 2)
    try:
        wert_setzen(*args.schluessel.split("."), args.wert)
    except ValueError as e:
        _abbruch(str(e), 1)
    print(f"{args.schluessel} gesetzt.")


def _auswahl_ergaenzen(args) -> None:
    try:
        ergaenzt = auswahl_ergaenzen()
    except ValueError as e:
        _abbruch(str(e), 1)
    print(f"Auswahl ergänzt: {', '.join(ergaenzt)}" if ergaenzt else "Auswahl ist vollständig.")


def _standard_vorschlag(args) -> None:
    bereit = {z.name for z in erkennung.zustaende(neu=True) if z.zustand == "bereit"}
    standard = next((n for n in REIHENFOLGE if n in bereit), "")
    if args.json:
        _ausgeben({"standard": standard})
    elif standard:
        print(standard)  # nur der Name, damit Skripte ihn direkt übernehmen können
    else:
        print("Keine KI ist bereit.", file=sys.stderr)
    if not standard:
        sys.exit(1)


def eintragen(subparsers) -> None:
    """Trägt den Unterbefehl `ki` mit seinen Befehlen ein."""
    ki = subparsers.add_parser("ki", help="KIs prüfen und einrichten")
    sub = ki.add_subparsers(dest="ki_cmd", required=True)

    def befehl(name: str, fn, hilfe: str, mit_json: bool = False) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=hilfe)
        p.set_defaults(fn=fn)
        if mit_json:
            p.add_argument("--json", action="store_true")
        return p

    befehl("zustand", _zustand, "Zustand der KIs", True).add_argument("name", nargs="?", choices=REIHENFOLGE)
    befehl("modelle", _modelle, "Vorschläge für das lokale Modell", True)
    befehl("gemini-pruefen", _gemini_pruefen, "Schlüssel von stdin prüfen und speichern")
    setzen = befehl("setzen", _setzen, "Einstellung in config.toml ändern")
    setzen.add_argument("schluessel", metavar="abschnitt.schluessel")
    setzen.add_argument("wert")
    befehl("auswahl-ergaenzen", _auswahl_ergaenzen, "fehlende KIs in [modell] auswahl ergänzen")
    befehl("standard-vorschlag", _standard_vorschlag, "erste bereite KI", True)
