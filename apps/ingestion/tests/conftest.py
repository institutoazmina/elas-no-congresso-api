import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def _reset_theme_cache():
    """Isola o cache de termos do theme_assert entre os testes."""
    from apps.ingestion.theme_assert import invalidate_cache

    invalidate_cache()
    yield
    invalidate_cache()


@pytest.fixture
def load_fixture():
    def _load(name: str):
        return json.loads((FIXTURES_DIR / name).read_text())

    return _load


@pytest.fixture
def camara_payload(load_fixture):
    return {
        "summary": load_fixture("camara_summary.json"),
        "detail": load_fixture("camara_detail.json"),
        "authors": load_fixture("camara_authors.json"),
        "deputy": load_fixture("camara_deputy.json"),
    }


@pytest.fixture
def senado_payload(load_fixture):
    return {
        "summary": load_fixture("senado_summary.json"),
        "detail": load_fixture("senado_detail.json"),
        "movements": load_fixture("senado_movements.json"),
        "texts": load_fixture("senado_texts.json"),
        "autoria": load_fixture("senado_autoria.json"),
    }
