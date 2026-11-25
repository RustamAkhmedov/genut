"""Vorschläge für das lokale Modell mit Urteil zum Rechner (research.md R6)."""
from __future__ import annotations

import math
from collections.abc import Iterable

from .daten import Modell, Modellvorschlag, Rechnerprofil, modelle_laden

RESERVE_GB = 4  # was System und andere Programme vom Arbeits- bzw. gemeinsamen Speicher brauchen
PLATZ_PUFFER_GB = 2


def _gb(wert: float) -> str:
    """Deutsche Zahl mit höchstens einer Nachkommastelle. Rundet ab, damit nie
    „braucht 10 GB, du hast 10 GB“ entsteht, obwohl knapp etwas fehlt."""
    return f"{math.floor(wert * 10 + 1e-6) / 10:g}".replace(".", ",")


def _urteil(profil: Rechnerprofil, modell: Modell) -> tuple[str, str]:
    bedarf = modell.bedarf_gb
    if profil.grafik == "apple":
        speicher, vorhanden, noetig = "gemeinsamen Speicher", profil.grafik_gb, bedarf + RESERVE_GB
    else:
        speicher, vorhanden, noetig = "Grafikspeicher", profil.grafik_gb, bedarf
    if profil.grafik != "keine" and vorhanden >= noetig:
        return "gut", f"Läuft gut: braucht {_gb(noetig)} GB {speicher}, du hast {_gb(vorhanden)} GB."

    ram_noetig = bedarf + RESERVE_GB
    if profil.ram_gb >= ram_noetig:
        if profil.grafik == "keine":
            grund = "ohne passende Grafikkarte"
        else:
            grund = f"braucht {_gb(noetig)} GB {speicher}, du hast {_gb(vorhanden)} GB"
        return "langsam", (f"Läuft langsam: {grund}; dein Arbeitsspeicher reicht "
                           f"({_gb(profil.ram_gb)} GB, nötig sind {_gb(ram_noetig)} GB).")

    grund = f"braucht {_gb(ram_noetig)} GB Arbeitsspeicher, du hast {_gb(profil.ram_gb)} GB"
    if profil.grafik in ("nvidia", "amd"):
        grund += f" (oder {_gb(noetig)} GB Grafikspeicher, du hast {_gb(vorhanden)} GB)"
    return "zu_gross", f"Zu groß: {grund}."


def vorschlaege(profil: Rechnerprofil, vorhandene: Iterable[str] = ()) -> list[Modellvorschlag]:
    """Genau drei Vorschläge in der Reihenfolge aus `modelle.toml`, genau einer vorgewählt."""
    vorhandene = set(vorhandene)
    liste = []
    for modell in modelle_laden():
        urteil, begruendung = _urteil(profil, modell)
        liste.append(Modellvorschlag(
            **modell.model_dump(),
            urteil=urteil,
            begruendung=begruendung,
            platz_warnung=(profil.frei_gb is not None
                           and profil.frei_gb < modell.download_gb + PLATZ_PUFFER_GB),
            vorhanden=modell.name in vorhandene,
        ))
    # Die Liste ist nach Bedarf aufsteigend sortiert: das letzte „gut“ ist das größte.
    wahl = next((v for v in reversed(liste) if v.urteil == "gut"), liste[0])
    wahl.vorgewaehlt = True
    return liste


def keins_gut(liste: list[Modellvorschlag]) -> bool:
    """Wahr, wenn kein Vorschlag gut läuft; dann empfiehlt der Dialog Gemini."""
    return all(v.urteil != "gut" for v in liste)
