"""Nach einem Update darf der Browser keine alte Oberfläche aus seinem Cache zeigen. Eine alte index.html
zum neuen app.js ergab eine leere Projektliste."""
import re

import pytest
from fastapi.testclient import TestClient

from genut.server import UI, app

client = TestClient(app)


def test_start_fuehrt_auf_neue_adressen():
    """Die alten Adressen (`/ui/`, `app.js`) liegen noch ohne Prüfpflicht im Cache: Es braucht neue."""
    ziel = client.get("/", follow_redirects=False).headers["location"]
    assert re.fullmatch(r"/ui/\?v=\d+", ziel)
    html = (UI / "index.html").read_text(encoding="utf-8")
    stand = ziel.split("=")[1]
    for datei in ("app.css", "app.js", "tex_sicher.js"):
        assert f'"{datei}?v={stand}"' in html, datei


@pytest.mark.parametrize("pfad", ["/ui/", "/ui/?v=3", "/ui/app.js?v=3", "/ui/app.css", "/ui/funktionen/lernplan.js"])
def test_oberflaeche_wird_bei_jedem_laden_geprueft(pfad):
    r = client.get(pfad)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
    nochmal = client.get(pfad, headers={"If-None-Match": r.headers["etag"]})
    assert nochmal.status_code == 304 and nochmal.headers["cache-control"] == "no-cache"
