"""TeX-Stellen einsammeln und mit node/tex_check.js prüfen."""
from __future__ import annotations

import json
import re
import subprocess

from ..config import WURZEL

TEX_RE = re.compile(r"\\\((.+?)\\\)|\\\[(.+?)\\\]", re.S)


def aus_md(md: str | None) -> list[tuple[str, bool]]:
    if not md:
        return []
    return [(m.group(1) if m.group(1) is not None else m.group(2), m.group(2) is not None)
            for m in TEX_RE.finditer(md)]


def pruefen(eintraege: list[dict]) -> dict[str, list[str]]:
    """eintraege: [{id, tex, display}] → {id: [meldung, …]} für fehlerhafte."""
    if not eintraege:
        return {}
    r = subprocess.run(["node", str(WURZEL / "node" / "tex_check.js")], input=json.dumps(eintraege),
                       capture_output=True, text=True, cwd=WURZEL, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"tex_check.js fehlgeschlagen: {r.stderr[-500:]}")
    fehler: dict[str, list[str]] = {}
    for f in json.loads(r.stdout):
        fehler.setdefault(f["id"], []).append(f"TeX-Fehler in {f['tex'][:80]!r}: {f['fehler']}")
    return fehler
