"""Veröffentlichen auf GitHub Pages. Niemals --force."""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from .config import laden
from .projekt import Projekt, atomar_schreiben
from .render.pages_index import index_html


class ExportFehler(Exception):
    pass


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    if r.returncode != 0:
        raise ExportFehler(f"git {' '.join(args)}: {(r.stderr or r.stdout).strip()[-600:]}")
    return r.stdout


def pages_ziel() -> tuple[Path, str]:
    cfg = laden()["pages"]
    if not cfg.get("repo_pfad"):
        raise ExportFehler("In config.toml ist [pages] repo_pfad nicht gesetzt (siehe README)")
    repo = Path(cfg["repo_pfad"]).expanduser()
    basis = cfg.get("basis_url") or ""
    if basis and not basis.endswith("/"):
        basis += "/"
    return repo, basis


def vorschau(p: Projekt) -> dict:
    repo, basis = pages_ziel()
    return {"repo": str(repo), "url": basis + p.slug + "/",
            "dateien": [f"{p.slug}/index.html", "seiten.json", "index.html"]}


def veroeffentlichen(p: Projekt, repo: Path | None = None, basis: str | None = None) -> str:
    if repo is None:
        repo, basis = pages_ziel()
    basis = basis or ""
    if not p.ausgabe.exists():
        raise ExportFehler("Die Seite wurde noch nicht gebaut")
    if not (repo / ".git").exists():
        raise ExportFehler(f"{repo} ist kein git-Repository")
    if _git(repo, "status", "--porcelain").strip():
        raise ExportFehler(f"Arbeitsbaum in {repo} ist nicht sauber – bitte erst committen oder aufräumen")
    hat_remote = bool(_git(repo, "remote").strip())
    hat_commit = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=repo, capture_output=True).returncode == 0
    if hat_remote and hat_commit:
        _git(repo, "pull", "--ff-only")

    ziel = repo / p.slug / "index.html"
    ziel.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p.ausgabe, ziel)

    doc = p.inhalt()
    manifest_pfad = repo / "seiten.json"
    seiten = json.loads(manifest_pfad.read_text(encoding="utf-8")) if manifest_pfad.exists() else []
    seiten = [s for s in seiten if s.get("slug") != p.slug]
    jetzt = datetime.now().isoformat(timespec="seconds")
    seiten.append({"slug": p.slug, "titel": doc.projekt.titel, "untertitel": doc.projekt.untertitel,
                   "fach": doc.projekt.fach, "aktualisiert": jetzt})
    seiten.sort(key=lambda s: s["aktualisiert"], reverse=True)
    atomar_schreiben(manifest_pfad, json.dumps(seiten, ensure_ascii=False, indent=2))
    atomar_schreiben(repo / "index.html", index_html(seiten))

    _git(repo, "add", f"{p.slug}/index.html", "seiten.json", "index.html")
    _git(repo, "commit", "-m", f"Lernseite {doc.projekt.titel} aktualisiert")
    if hat_remote:
        _git(repo, "push")

    url = basis + p.slug + "/"
    m = p.meta()
    m.pages.veroeffentlicht, m.pages.zuletzt, m.pages.url = True, jetzt, url
    p.meta_speichern(m)
    return url
