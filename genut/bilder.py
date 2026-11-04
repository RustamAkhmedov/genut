"""Fotos vorbereiten (EXIF-Drehung, Verkleinern, HEIC) und Ausschnitte für bild-Blöcke."""
from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image, ImageOps

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # HEIC dann nicht verfügbar
    pass

MAX_SEITE = 2000
ENDUNGEN = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}


def vorbereiten(quelle: Path, ziel: Path) -> None:
    with Image.open(quelle) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):  # Screenshots mit Transparenz
            im = im.convert("RGBA")
            weiss = Image.new("RGB", im.size, (255, 255, 255))
            weiss.paste(im, mask=im.getchannel("A"))
            im = weiss
        im = im.convert("RGB")
        im.thumbnail((MAX_SEITE, MAX_SEITE))
        ziel.parent.mkdir(parents=True, exist_ok=True)
        im.save(ziel, "JPEG", quality=88)


def ausschnitt_base64(foto: Path, bbox: list[float], max_breite: int = 1200) -> str:
    with Image.open(foto) as im:
        w, h = im.size
        x, y, b, hh = bbox
        box = (max(0, int(x * w)), max(0, int(y * h)), min(w, int((x + b) * w)), min(h, int((y + hh) * h)))
        teil = im.crop(box)
        if teil.width > max_breite:
            teil = teil.resize((max_breite, round(teil.height * max_breite / teil.width)))
        buf = io.BytesIO()
        teil.save(buf, "WEBP", quality=80)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
