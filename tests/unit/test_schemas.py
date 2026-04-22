import pytest
from django.contrib.auth import get_user_model

from apps.legislatures.schemas import ParliamentarianSchema
from apps.propositions.schemas import PropositionSchema
from apps.taxonomy.schemas import ThemeSchema

User = get_user_model()


@pytest.fixture
def django_db(django_db):
    return django_db


@pytest.mark.django_db
class TestPropositionSchema:
    def test_model_schema_creation(self):
        schema = PropositionSchema.model_fields
        assert "id" in schema
        assert "number" in schema
        assert "year" in schema
        assert "ementa" in schema

    def test_excludes_fields(self):
        assert "search_vector" not in PropositionSchema.model_fields
        assert "raw_payload" not in PropositionSchema.model_fields


@pytest.mark.django_db
class TestParliamentarianSchema:
    def test_model_schema_creation(self):
        schema = ParliamentarianSchema.model_fields
        assert "id" in schema
        assert "full_name" in schema
        assert "gender" in schema


@pytest.mark.django_db
class TestThemeSchema:
    def test_model_schema_creation(self):
        schema = ThemeSchema.model_fields
        assert "id" in schema
        assert "slug" in schema
        assert "name" in schema
