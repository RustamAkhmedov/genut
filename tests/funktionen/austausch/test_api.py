"""HTTP-Routen des Projekt-Austauschs (contracts/api.md)."""
import anyio
import pytest
from fastapi.testclient import TestClient

from genut.config import laden
from genut.pipeline import Pipeline
from genut.projekt import Projekt
from genut.server import app

from .hilfen import gutes_paket, paket_html

SEITE = "<!doctype html>\n<html><body><main>Seite</main></body></html>\n"
BLOCK = '<script type="application/json" id="genutQuelle">'


@pytest.fixture
def c():
    return TestClient(app)


@pytest.fixture
def p(projekt_mit_inhalt):
    projekt_mit_inhalt.ausgabe.write_text(SEITE, encoding="utf-8")
    return projekt_mit_inhalt


def _url(slug):
    return f"/api/austausch/projekte/{slug}/download"


def test_download_mit_datenblock(c, p):
    vorher = p.ausgabe.read_bytes()
    r = c.get(_url(p.slug))
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/html; charset=utf-8"
    assert r.headers["content-disposition"] == f'attachment; filename="{p.slug}.html"'
    assert r.text.count(BLOCK) == 1 and 'class="genut-austausch"' in r.text
    assert p.ausgabe.read_bytes() == vorher  # FR-009


def test_gemeinsamer_download_ohne_datenblock(c, p):
    r = c.get(f"/api/projekte/{p.slug}/download")
    assert r.status_code == 200 and r.content == p.ausgabe.read_bytes()
    assert BLOCK not in r.text and "genut-austausch" not in r.text


@pytest.mark.parametrize("slug", ["gibt-es-nicht", "Ungueltig_!"])
def test_download_unbekanntes_projekt(c, p, slug):
    r = c.get(_url(slug))
    assert r.status_code == 404 and r.json() == {"detail": "Projekt nicht gefunden"}


def test_download_ohne_gebaute_seite(c, p):
    p.ausgabe.unlink()
    r = c.get(_url(p.slug))
    assert r.status_code == 404 and r.json() == {"detail": "Noch keine Seite gebaut"}


def test_schalter_aus_404(c, p, monkeypatch, tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[funktionen]\naustausch = false\n", encoding="utf-8")
    monkeypatch.setenv("GENUT_CONFIG", str(cfg))
    laden.cache_clear()
    try:
        r = c.get(_url(p.slug))
        assert r.status_code == 404 and r.json() == {"detail": "Not Found"}
        assert c.get(f"/api/projekte/{p.slug}/download").status_code == 200
    finally:
        monkeypatch.undo()
        laden.cache_clear()


# ---------------------------------------------------------------- Import und Herkunft

KOPF = {"X-Genut": "1", "Host": "127.0.0.1:80"}
IMPORT = "/api/austausch/import"
MB30 = 30 * 1024 * 1024
ZU_GROSS = {"detail": "Die Datei ist größer als 30 MB."}
KEINE_DATEI = {"detail": "Keine Datei übergeben."}


@pytest.fixture
def attrappe(monkeypatch):
    monkeypatch.setattr(Pipeline, "pruefen_bauen", lambda self, ids=None: {"status": {"ok": 2, "fehler": 1}})


def _anzahl(projekte) -> int:
    return len(list(projekte.iterdir()))


def _senden(c, daten: bytes, kopf=KOPF, name="chemie.html"):
    return c.post(IMPORT, headers=kopf, files={"datei": (name, daten, "text/html")})


def test_import_200_und_herkunft(c, p, projekte, attrappe):
    assert c.get("/api/austausch/herkunft").json() == {"projekte": {}}
    r = _senden(c, c.get(_url(p.slug)).content)
    assert r.status_code == 200, r.text
    slug = f"{p.slug}-2"
    assert r.json() == {"slug": slug, "name": "Test Integral", "status": {"ok": 2, "fehler": 1}, "warnung": None}
    herkunft = c.get("/api/austausch/herkunft").json()["projekte"]
    assert list(herkunft) == [slug]
    assert set(herkunft[slug]) == {"importiert_am", "dateiname", "format"}
    assert herkunft[slug]["dateiname"] == "chemie.html" and herkunft[slug]["format"] == 1


@pytest.mark.parametrize("herkunftszeile", [{"Origin": "http://127.0.0.1:80"}, {"Host": "localhost:80"}])
def test_import_erlaubte_kopfzeilen(c, p, attrappe, herkunftszeile):
    assert _senden(c, paket_html(gutes_paket(p)), KOPF | herkunftszeile).status_code == 200


def test_import_seite_ohne_daten(c, p, projekte):
    vorher = _anzahl(projekte)
    r = _senden(c, p.ausgabe.read_bytes())
    assert r.status_code == 400
    assert r.json() == {"detail": "Diese Datei enthält keine Projektdaten. Bitte den Absender, sie mit dem Haken "
                                  "„Zum Importieren für Freunde“ neu herunterzuladen."}
    assert _anzahl(projekte) == vorher


@pytest.mark.parametrize("anfrage", [
    {},
    {"data": {"datei": "nur Text"}},
    {"files": {"anders": ("a.html", b"x")}},
    {"files": [("datei", ("a.html", b"x")), ("datei", ("b.html", b"y"))]},  # zu viele Dateien
    {"files": {"datei": ("a.html", b"x")}, "data": {f"f{i}": "x" for i in range(6)}},  # zu viele Felder
    {"content": b"x", "headers": {"Content-Type": "multipart/form-data"}},  # ohne boundary
    {"content": b"kaputt", "headers": {"Content-Type": "multipart/form-data; boundary=abc"}},
    {"data": {"gross": "x" * (2 * 1024 * 1024)}, "files": {"datei": ("a.html", b"x")}},  # Feld über 1 MB
])
def test_import_ohne_datei(c, p, projekte, anfrage):
    vorher = _anzahl(projekte)
    r = c.post(IMPORT, **(anfrage | {"headers": KOPF | anfrage.get("headers", {})}))
    assert r.status_code == 400 and r.json() == KEINE_DATEI, r.text
    assert _anzahl(projekte) == vorher


def _multipart(daten: bytes) -> tuple[bytes, str]:
    kopf = b'--grenze\r\nContent-Disposition: form-data; name="datei"; filename="a.html"\r\n\r\n'
    return kopf + daten + b"\r\n--grenze--\r\n", "multipart/form-data; boundary=grenze"


@pytest.mark.parametrize("mit_laenge", [True, False])
@pytest.mark.parametrize("groesse", [MB30 + 1, MB30 + 100_000])
def test_import_zu_gross(c, p, projekte, mit_laenge, groesse):
    vorher = _anzahl(projekte)
    koerper, typ = _multipart(b"x" * groesse)
    # ein Iterator als Körper wird ohne Content-Length (chunked) geschickt
    r = c.post(IMPORT, headers=KOPF | {"Content-Type": typ}, content=koerper if mit_laenge else iter([koerper]))
    assert ("content-length" in r.request.headers) == mit_laenge
    assert r.status_code == 413 and r.json() == ZU_GROSS
    assert _anzahl(projekte) == vorher


def _asgi_import(kopf: dict, stuecke) -> tuple[int, int]:
    """Ruft die App direkt auf, damit sich zählen lässt, wie viel sie wirklich liest.
    Liefert (Status, gelesene Nachrichten)."""
    gelesen, status = 0, []

    async def receive():
        nonlocal gelesen
        stueck = next(stuecke, None)
        gelesen += 1
        return {"type": "http.request", "body": stueck or b"", "more_body": stueck is not None}

    async def send(nachricht):
        if nachricht["type"] == "http.response.start":
            status.append(nachricht["status"])

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http",
             "path": IMPORT, "raw_path": IMPORT.encode(), "query_string": b"", "root_path": "",
             "server": ("127.0.0.1", 80), "client": ("127.0.0.1", 5000),
             "headers": [(k.lower().encode(), v.encode()) for k, v in kopf.items()]}
    anyio.run(app, scope, receive, send)
    return status[0], gelesen


def _endlos(erstes: bytes):
    yield erstes
    block = b"x" * (1024 * 1024)
    for _ in range(100):
        yield block


def test_endloser_koerper_ohne_laenge_wird_abgebrochen(projekte):
    anfang, typ = _multipart(b"")
    anfang = anfang.split(b"\r\n\r\n")[0] + b"\r\n\r\n"
    status, gelesen = _asgi_import(KOPF | {"Content-Type": typ}, _endlos(anfang))
    assert status == 413 and gelesen <= 32  # nach gut 30 MB ist Schluss, nicht erst nach 100
    assert not projekte.exists() or _anzahl(projekte) == 0


@pytest.mark.parametrize("kopf,erwartet", [
    ({"Host": "127.0.0.1:80", "Content-Length": "1000"}, 403),
    (KOPF | {"Content-Length": str(MB30 + 64 * 1024 + 1)}, 413),
])
def test_abgewiesen_ohne_den_koerper_zu_lesen(kopf, erwartet):
    typ = "multipart/form-data; boundary=grenze"
    assert _asgi_import(kopf | {"Content-Type": typ}, _endlos(b"x")) == (erwartet, 0)


@pytest.mark.parametrize("kopf", [
    {"Host": "127.0.0.1:80"},
    KOPF | {"Host": "evil.example:80"},
    KOPF | {"Origin": "http://evil.example"},
])
def test_import_schreibschutz(c, p, projekte, kopf):
    vorher = _anzahl(projekte)
    r = _senden(c, paket_html(gutes_paket(p)), kopf)
    assert r.status_code == 403
    assert r.json() == {"detail": "Anfrage abgelehnt: Sie kommt nicht aus der gen_Ut-Oberfläche"}
    assert _anzahl(projekte) == vorher


def test_import_500_ohne_reste(c, p, projekte, monkeypatch):
    daten, vorher = paket_html(gutes_paket(p)), _anzahl(projekte)

    def kaputt(self, doc):
        raise OSError("Platte voll")

    monkeypatch.setattr(Projekt, "inhalt_speichern", kaputt)
    r = _senden(c, daten)
    assert r.status_code == 500
    assert r.json() == {"detail": "Import fehlgeschlagen, es wurde nichts angelegt: Platte voll"}
    assert _anzahl(projekte) == vorher


def test_import_und_herkunft_schalter_aus(c, p, projekte, monkeypatch, tmp_path):
    daten, vorher = paket_html(gutes_paket(p)), _anzahl(projekte)
    cfg = tmp_path / "config.toml"
    cfg.write_text("[funktionen]\naustausch = false\n", encoding="utf-8")
    monkeypatch.setenv("GENUT_CONFIG", str(cfg))
    laden.cache_clear()
    try:
        assert _senden(c, daten).status_code == 404
        assert c.get("/api/austausch/herkunft").status_code == 404
        assert _anzahl(projekte) == vorher
    finally:
        monkeypatch.undo()
        laden.cache_clear()
