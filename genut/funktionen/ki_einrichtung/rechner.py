"""Rechnerprofil für die Modellwahl (specs/005b-ein-genut/research.md R7).
Bleibt lokal und wird nirgends gespeichert. Alle GB-Werte sind GiB.
Jede Quelle hat ein Zeitlimit; was fehlt, gilt als nicht vorhanden."""
from __future__ import annotations

import ctypes
import os
import platform
import shutil
import subprocess
import threading
from pathlib import Path

from .daten import Rechnerprofil

ZEITLIMIT = 3.0
MEMINFO = Path("/proc/meminfo")
DRM = Path("/sys/class/drm")
# Geräteklasse „Grafikkarte“ in der Windows-Registry
GRAFIK_SCHLUESSEL = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
_SYSTEME = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}
_GIB = 1024 ** 3


def profil() -> Rechnerprofil:
    system = _SYSTEME.get(platform.system(), "linux")
    ram_quelle = {"linux": _ram_linux, "macos": _ram_macos, "windows": _ram_windows}[system]
    ram_gb = _quelle(ram_quelle, 0.0)
    grafik, name, grafik_gb = _grafik(system, ram_gb)
    return Rechnerprofil(
        ram_gb=ram_gb, grafik=grafik, grafik_name=name, grafik_gb=grafik_gb,
        system=system, frei_gb=_quelle(_frei, None),
    )


def _quelle(fn, ersatz):
    """Führt eine Quelle mit Zeitlimit aus; Fehler oder Zeitüberschreitung ergeben `ersatz`."""
    ergebnis = [ersatz]

    def lauf():
        try:
            ergebnis[0] = fn()
        except Exception:  # jede Quelle darf ausfallen
            pass

    thread = threading.Thread(target=lauf, daemon=True)
    thread.start()
    thread.join(ZEITLIMIT)
    return ersatz if thread.is_alive() else ergebnis[0]


def _gb(anzahl_bytes: float) -> float:
    return round(anzahl_bytes / _GIB, 1)


def _befehl(*teile: str) -> str:
    return subprocess.run(
        list(teile), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=ZEITLIMIT, check=True
    ).stdout


def _ram_linux() -> float:
    for zeile in MEMINFO.read_text(encoding="utf-8").splitlines():
        if zeile.startswith("MemTotal:"):
            return _gb(int(zeile.split()[1]) * 1024)
    return 0.0


def _ram_macos() -> float:
    return _gb(int(_befehl("sysctl", "-n", "hw.memsize").strip()))


def _ram_windows() -> float:
    class Speicherstatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            *((feld, ctypes.c_ulonglong) for feld in (
                "ullTotalPhys", "ullAvailPhys", "ullTotalPageFile", "ullAvailPageFile",
                "ullTotalVirtual", "ullAvailVirtual", "ullAvailExtendedVirtual")),
        ]

    status = Speicherstatus(dwLength=ctypes.sizeof(Speicherstatus))
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return 0.0
    return _gb(status.ullTotalPhys)


def _grafik(system: str, ram_gb: float) -> tuple[str, str, float]:
    """(Art, Name, Grafikspeicher in GB)."""
    if system == "macos" and platform.machine() == "arm64":
        return "apple", "Apple Silicon", ram_gb  # gemeinsamer Speicher
    karte = _quelle(_nvidia, None)
    if karte:
        return ("nvidia", *karte)
    ersatz = {"linux": _amd_linux, "windows": _amd_windows}.get(system)
    karte = _quelle(ersatz, None) if ersatz else None
    if karte:
        return ("amd", *karte)
    return "keine", "", 0.0


def _groesste(karten: list[tuple[str, float]]) -> tuple[str, float] | None:
    return max(karten, key=lambda k: k[1], default=None)


def _nvidia() -> tuple[str, float] | None:
    ausgabe = _befehl("nvidia-smi", "--query-gpu=name,memory.total",
                      "--format=csv,noheader,nounits")
    karten = []
    for zeile in ausgabe.splitlines():
        name, _, mib = zeile.rpartition(",")
        if name and mib.strip().isdigit():  # z. B. „[N/A]“ überspringen
            karten.append((name.strip(), _gb(int(mib) * 1024 ** 2)))
    return _groesste(karten)


def _amd_linux() -> tuple[str, float] | None:
    karten = []
    for datei in DRM.glob("card*/device/mem_info_vram_total"):
        try:
            karten.append(("AMD-Grafikkarte", _gb(int(datei.read_text(encoding="utf-8").strip()))))
        except (OSError, ValueError):
            continue
    return _groesste(karten)


def _amd_windows() -> tuple[str, float] | None:
    """Nur AMD zählt; integrierte Intel-Grafik gilt als keine Grafikkarte."""
    import winreg

    karten = []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, GRAFIK_SCHLUESSEL) as klasse:
        for i in range(winreg.QueryInfoKey(klasse)[0]):
            try:
                with winreg.OpenKey(klasse, winreg.EnumKey(klasse, i)) as geraet:
                    name = str(winreg.QueryValueEx(geraet, "DriverDesc")[0])
                    wert = winreg.QueryValueEx(geraet, "HardwareInformation.qwMemorySize")[0]
            except OSError:  # Unterschlüssel ohne diese Werte oder ohne Zugriff
                continue
            if isinstance(wert, bytes):  # manche Treiber schreiben REG_BINARY
                wert = int.from_bytes(wert, "little")
            if "amd" in name.lower() or "radeon" in name.lower():
                karten.append((name, _gb(wert)))
    return _groesste(karten)


def _frei() -> float:
    """Freier Platz im Modellordner von Ollama bzw. im nächsten vorhandenen Elternordner."""
    eigen = os.environ.get("OLLAMA_MODELS")
    ordner = Path(eigen).expanduser() if eigen else Path.home() / ".ollama" / "models"
    ordner = ordner.absolute()
    while not ordner.exists() and ordner != ordner.parent:
        ordner = ordner.parent
    return _gb(shutil.disk_usage(ordner).free)
