import shutil
from pathlib import Path

import pytest

from genut.schema import Dokument

FIX = Path(__file__).parent / "fixtures" / "integral"


@pytest.fixture
def doc() -> Dokument:
    return Dokument.model_validate_json((FIX / "inhalt.json").read_text(encoding="utf-8"))


@pytest.fixture
def projekte(tmp_path, monkeypatch):
    monkeypatch.setenv("GENUT_PROJEKTE", str(tmp_path / "projekte"))
    return tmp_path / "projekte"


@pytest.fixture
def projekt_mit_inhalt(projekte):
    from genut.projekt import Projekt

    p = Projekt.anlegen("Test Integral")
    shutil.copy(FIX / "fotos" / "001.jpg", p.fotos / "001.jpg")
    p.inhalt_speichern(Dokument.model_validate_json((FIX / "inhalt.json").read_text(encoding="utf-8")))
    return p
