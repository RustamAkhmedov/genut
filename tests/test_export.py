from pathlib import Path
import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from genut import export
from genut.pipeline import Pipeline


def _git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def pages_repo(tmp_path):
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(bare))
    klon = tmp_path / "lernseiten"
    _git(tmp_path, "clone", str(bare), str(klon))
    _git(klon, "config", "user.email", "test@example.com")
    _git(klon, "config", "user.name", "Test")
    return bare, klon


def test_veroeffentlichen(projekt_mit_inhalt, pages_repo):
    bare, klon = pages_repo
    p = projekt_mit_inhalt
    Pipeline(p).pruefen_bauen()
    url = export.veroeffentlichen(p, klon, "https://beispiel.github.io/lernseiten/")
    assert url == f"https://beispiel.github.io/lernseiten/{p.slug}/"
    assert (klon / p.slug / "index.html").exists()
    seiten = json.loads((klon / "seiten.json").read_text(encoding="utf-8"))
    assert seiten[0]["slug"] == p.slug
    assert p.slug in (klon / "index.html").read_text(encoding="utf-8")
    assert "Lernseite" in _git(bare, "log", "--oneline", "main")
    assert p.meta().pages.veroeffentlicht


def test_unsauberer_baum_bricht_ab(projekt_mit_inhalt, pages_repo):
    _, klon = pages_repo
    Pipeline(projekt_mit_inhalt).bauen()
    (klon / "fremd.txt").write_text("x")
    with pytest.raises(export.ExportFehler, match="nicht sauber"):
        export.veroeffentlichen(projekt_mit_inhalt, klon, "")


def _config(monkeypatch, tmp_path, text):
    from genut.config import laden
    cfg = tmp_path / "config.toml"
    cfg.write_text(text, encoding="utf-8")
    monkeypatch.setenv("GENUT_CONFIG", str(cfg))
    laden.cache_clear()


def test_api_verlangt_bestaetigung(projekt_mit_inhalt, monkeypatch, tmp_path):
    from genut.config import laden
    from genut.server import app

    _config(monkeypatch, tmp_path, "[pages]\naktiv = true\n")
    try:
        c = TestClient(app)
        r = c.post(f"/api/projekte/{projekt_mit_inhalt.slug}/pages", json={})
        assert r.status_code == 400 and "bestätigt" in r.json()["detail"]
    finally:
        laden.cache_clear()


def test_pages_in_oeffentlichen_versionen_aus(projekt_mit_inhalt, monkeypatch, tmp_path):
    """Ohne [pages] aktiv = true (öffentliche Versionen) gibt es keinen Pages-Export."""
    from genut.config import laden
    from genut.server import app

    for version in ("claude", "gemini", "lokal"):
        _config(monkeypatch, tmp_path, (Path(__file__).parent.parent / "versionen" / f"{version}.toml").read_text(encoding="utf-8"))
        try:
            c = TestClient(app)
            assert c.get(f"/api/projekte/{projekt_mit_inhalt.slug}/pages").status_code == 404
            assert c.post(f"/api/projekte/{projekt_mit_inhalt.slug}/pages", json={"bestaetigt": True}).status_code == 404
            ki = c.get("/api/ki").json()
            assert ki["pages"] is False and ki["standard"] in ki["auswahl"]
        finally:
            laden.cache_clear()


def test_api_json_editor(projekt_mit_inhalt):
    from genut.server import app

    c = TestClient(app)
    slug = projekt_mit_inhalt.slug
    doc = c.get(f"/api/projekte/{slug}/inhalt").json()
    doc["themen"][0]["bloecke"][0]["quelle"] = "unsinn"
    r = c.put(f"/api/projekte/{slug}/inhalt", content=json.dumps(doc))
    assert r.status_code == 400 and "themen.0.bloecke.0" in json.dumps(r.json(), ensure_ascii=False)
    doc["themen"][0]["bloecke"][0]["quelle"] = "foto"
    doc["themen"][0]["bloecke"][0]["md"] = "Vom Nutzer geändert"
    r = c.put(f"/api/projekte/{slug}/inhalt", content=json.dumps(doc))
    assert r.status_code == 200, r.text
    assert r.json()["geaendert"] == ["b-00000001"]
    neu = c.get(f"/api/projekte/{slug}/elemente/b-00000001").json()["element"]
    assert neu["gesperrt"] is True and neu["md"] == "Vom Nutzer geändert"
