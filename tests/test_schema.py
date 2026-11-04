import json

import pytest
from pydantic import ValidationError

from genut.schema import Dokument, Korrektur, Patch, ki_schema


def test_fixture_ist_gueltig(doc):
    assert len(doc.themen) == 2
    typen = {b.typ for t in doc.themen for b in t.bloecke}
    assert {"text", "definition", "regel", "formel", "graph", "tabelle", "bild", "hinweis"} <= typen


def test_ki_schema_ohne_serverfelder():
    s = json.dumps(ki_schema(Patch))
    for feld in ('"id"', '"pruefung"', '"gesperrt"', '"ausdruck_js"', '"thema_id": {"type"'):
        assert feld not in s.replace('"thema_id": {"description"', "")  # thema_id nur bei NeuerBlock
    assert '"discriminator"' not in s and '"oneOf"' not in s


def test_ki_schema_objekte_geschlossen():
    s = ki_schema(Korrektur)

    def pruefen(k):
        if isinstance(k, dict):
            if k.get("type") == "object" and "properties" in k:
                assert k.get("additionalProperties") is False
            for v in k.values():
                pruefen(v)
        elif isinstance(k, list):
            for v in k:
                pruefen(v)

    pruefen(s)


def test_unbekannter_blocktyp_abgelehnt(doc):
    roh = json.loads(doc.model_dump_json())
    roh["themen"][0]["bloecke"][0]["typ"] = "quatsch"
    with pytest.raises(ValidationError):
        Dokument.model_validate(roh)


def test_zusatzfelder_abgelehnt(doc):
    roh = json.loads(doc.model_dump_json())
    roh["themen"][0]["bloecke"][0]["html"] = "<script>"
    with pytest.raises(ValidationError):
        Dokument.model_validate(roh)
