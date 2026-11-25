"""Rechnerprofil (research.md R7) mit nachgestellten Quellen."""
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from genut.funktionen.ki_einrichtung import rechner

GIB = 1024 ** 3
MEMINFO = "MemTotal:       16384000 kB\nMemFree:         1000000 kB\n"


@pytest.fixture
def pc(monkeypatch, tmp_path):
    """Linux mit 15,6 GB RAM, ohne Grafikkarte; `befehle` bestimmt die Unterprozesse."""
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(MEMINFO)
    drm = tmp_path / "drm"
    drm.mkdir()
    befehle, aufrufe = {}, []

    def run(teile, **kw):
        aufrufe.append((teile, kw))
        antwort = befehle.get(teile[0], FileNotFoundError(teile[0]))
        if isinstance(antwort, BaseException):
            raise antwort
        return subprocess.CompletedProcess(teile, 0, stdout=antwort, stderr="")

    monkeypatch.setattr(rechner.subprocess, "run", run)
    monkeypatch.setattr(rechner, "MEMINFO", meminfo)
    monkeypatch.setattr(rechner, "DRM", drm)
    monkeypatch.setattr(rechner.shutil, "disk_usage", lambda p: SimpleNamespace(free=50 * GIB))
    monkeypatch.setattr(rechner.platform, "system", lambda: "Linux")
    monkeypatch.setattr(rechner.platform, "machine", lambda: "x86_64")
    return SimpleNamespace(befehle=befehle, aufrufe=aufrufe, meminfo=meminfo, drm=drm,
                           tmp=tmp_path)


def _amd_karte(drm, nummer, inhalt):
    ordner = drm / f"card{nummer}" / "device"
    ordner.mkdir(parents=True)
    (ordner / "mem_info_vram_total").write_text(inhalt)


def test_linux_ohne_grafikkarte(pc):
    p = rechner.profil()
    assert (p.system, p.ram_gb, p.frei_gb) == ("linux", 15.6, 50.0)
    assert (p.grafik, p.grafik_name, p.grafik_gb) == ("keine", "", 0)


def test_nvidia_groesste_karte(pc):
    pc.befehle["nvidia-smi"] = (
        "NVIDIA GeForce GTX 1650, 4096\nNVIDIA GeForce RTX 3060, 12288\nKaputt, [N/A]\n")
    p = rechner.profil()
    assert (p.grafik, p.grafik_name, p.grafik_gb) == ("nvidia", "NVIDIA GeForce RTX 3060", 12.0)
    teile, kw = pc.aufrufe[0]
    assert teile == ["nvidia-smi", "--query-gpu=name,memory.total",
                     "--format=csv,noheader,nounits"]
    assert kw["timeout"] == 3


@pytest.mark.parametrize("fehler", [
    FileNotFoundError("nvidia-smi"),
    subprocess.TimeoutExpired("nvidia-smi", 3),
    subprocess.CalledProcessError(9, "nvidia-smi"),
])
def test_nvidia_smi_fehlt_oder_haengt(pc, fehler):
    pc.befehle["nvidia-smi"] = fehler
    assert rechner.profil().grafik == "keine"


def test_haengende_quelle_wird_abgebrochen(pc, monkeypatch):
    ende = threading.Event()
    monkeypatch.setattr(rechner, "ZEITLIMIT", 0.05)
    monkeypatch.setattr(rechner.shutil, "disk_usage", lambda p: ende.wait(10))
    try:
        assert rechner.profil().frei_gb is None
    finally:
        ende.set()


def test_amd_aus_sysfs(pc):
    _amd_karte(pc.drm, 0, f"{GIB // 2}\n")
    _amd_karte(pc.drm, 1, f"{16 * GIB}\n")
    _amd_karte(pc.drm, 2, "unlesbar\n")
    p = rechner.profil()
    assert (p.grafik, p.grafik_gb) == ("amd", 16.0)


def test_alle_quellen_fehlen(pc, monkeypatch):
    pc.meminfo.unlink()

    def kaputt(pfad):
        raise OSError

    monkeypatch.setattr(rechner.shutil, "disk_usage", kaputt)
    p = rechner.profil()
    assert (p.ram_gb, p.grafik, p.grafik_gb, p.frei_gb) == (0, "keine", 0, None)


def test_apple_silicon(pc, monkeypatch):
    monkeypatch.setattr(rechner.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(rechner.platform, "machine", lambda: "arm64")
    pc.befehle["sysctl"] = f"{16 * GIB}\n"
    p = rechner.profil()
    assert (p.system, p.ram_gb, p.grafik, p.grafik_gb) == ("macos", 16.0, "apple", 16.0)


def test_intel_mac(pc, monkeypatch):
    monkeypatch.setattr(rechner.platform, "system", lambda: "Darwin")
    pc.befehle["sysctl"] = f"{8 * GIB}\n"
    p = rechner.profil()
    assert (p.ram_gb, p.grafik) == (8.0, "keine")


def _windows(monkeypatch, geraete):
    """`geraete`: {Unterschlüssel: {Wertname: Wert}} der Grafik-Geräteklasse."""
    class Schluessel:
        def __init__(self, inhalt):
            self.inhalt = inhalt

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def oeffnen(eltern, name):
        if eltern == "HKLM":
            assert name == rechner.GRAFIK_SCHLUESSEL
            return Schluessel(geraete)
        return Schluessel(eltern.inhalt[name])

    def wert(schluessel, name):
        if name not in schluessel.inhalt:
            raise FileNotFoundError(name)
        return schluessel.inhalt[name], 0

    monkeypatch.setitem(sys.modules, "winreg", SimpleNamespace(
        HKEY_LOCAL_MACHINE="HKLM", OpenKey=oeffnen, QueryValueEx=wert,
        QueryInfoKey=lambda s: (len(s.inhalt), 0, 0),
        EnumKey=lambda s, i: list(s.inhalt)[i]))

    def speicherstatus(zeiger):
        zeiger._obj.ullTotalPhys = 32 * GIB
        return 1

    monkeypatch.setattr(rechner.platform, "system", lambda: "Windows")
    monkeypatch.setattr(rechner.ctypes, "windll", SimpleNamespace(
        kernel32=SimpleNamespace(GlobalMemoryStatusEx=speicherstatus)), raising=False)


INTEL = {"DriverDesc": "Intel(R) UHD Graphics 770",
         "HardwareInformation.qwMemorySize": 2 * GIB}


@pytest.mark.parametrize("speicher", [8 * GIB, (8 * GIB).to_bytes(8, "little")])
def test_windows_amd_aus_registry(pc, monkeypatch, speicher):
    _windows(monkeypatch, {
        "0000": INTEL,
        "0001": {"DriverDesc": "AMD Radeon RX 6600",
                 "HardwareInformation.qwMemorySize": speicher},
        "Properties": {},
    })
    p = rechner.profil()
    assert (p.system, p.ram_gb) == ("windows", 32.0)
    assert (p.grafik, p.grafik_name, p.grafik_gb) == ("amd", "AMD Radeon RX 6600", 8.0)


def test_windows_nur_intel(pc, monkeypatch):
    _windows(monkeypatch, {"0000": INTEL})
    assert rechner.profil().grafik == "keine"


def test_windows_nvidia_geht_vor(pc, monkeypatch):
    _windows(monkeypatch, {"0000": INTEL})
    pc.befehle["nvidia-smi"] = "NVIDIA GeForce RTX 4070, 12282\n"
    p = rechner.profil()
    assert (p.grafik, p.grafik_gb) == ("nvidia", 12.0)


@pytest.mark.parametrize("eigener_ordner", [True, False])
def test_freier_platz_im_naechsten_vorhandenen_ordner(pc, monkeypatch, eigener_ordner):
    gefragt = []
    monkeypatch.setattr(rechner.shutil, "disk_usage",
                        lambda p: gefragt.append(p) or SimpleNamespace(free=GIB))
    if eigener_ordner:
        monkeypatch.setenv("OLLAMA_MODELS", str(pc.tmp / "fehlt" / "modelle"))
        erwartet = pc.tmp
    else:
        monkeypatch.delenv("OLLAMA_MODELS", raising=False)
        monkeypatch.setattr(rechner.Path, "home", lambda: pc.tmp)
        (pc.tmp / ".ollama").mkdir()
        erwartet = pc.tmp / ".ollama"
    assert rechner.profil().frei_gb == 1.0
    assert gefragt == [erwartet]
