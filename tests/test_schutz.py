"""Gemeinsamer Schreibschutz (genut/schutz.py), unabhängig von den entfernbaren Funktionsmodulen."""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from genut.schutz import schreibschutz

APP = FastAPI()


@APP.post("/schreiben", dependencies=[Depends(schreibschutz)])
def _schreiben():
    return {"ok": True}


def _post(kopf: dict):
    # TestClient meldet als gebundenen Port 80, deshalb nennt auch der Host den Port 80
    return TestClient(APP).post("/schreiben", headers=kopf)


GUT = {"X-Genut": "1", "Host": "127.0.0.1:80"}


@pytest.mark.parametrize("kopf", [
    GUT,
    {**GUT, "Origin": "http://127.0.0.1:80"},
    {**GUT, "Host": "localhost:80"},
    {**GUT, "Host": "localhost:80", "Origin": "http://localhost:80"},
])
def test_eigene_oberflaeche_darf(kopf):
    r = _post(kopf)
    assert r.status_code == 200 and r.json() == {"ok": True}


@pytest.mark.parametrize("kopf", [
    {"Host": "127.0.0.1:80"},
    {**GUT, "X-Genut": "0"},
    {**GUT, "Host": "evil.example:80"},
    {**GUT, "Host": "127.0.0.1:9999"},
    {**GUT, "Origin": "http://evil.example"},
], ids=["ohne-kopfzeile", "kopfzeile-0", "fremder-host", "falscher-port", "fremder-origin"])
def test_alles_andere_ist_403(kopf):
    assert _post(kopf).status_code == 403
