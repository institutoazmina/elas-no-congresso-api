import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext

from apps.propositions.admin import PropositionAdmin
from apps.propositions.models import (
    ClassificationRequest,
    Proposition,
    PropositionAnalysis,
    PropositionAnnotation,
    PropositionContentVersion,
    PropositionEmbedding,
    PropositionEvent,
)
from apps.taxonomy.models import PropositionTheme, Theme


@pytest.mark.django_db
def test_proposition_list_displays_ementa_and_relevance_terms():
    proposition = Proposition.objects.create(
        house="camara",
        external_id=2,
        type_code="PL",
        number_label="PL 2/2026",
        number=2,
        year=2026,
        presented_at="2026-01-02",
        ementa="Protege mulheres vítimas de violência.",
    )
    second = Theme.objects.create(slug="mulher", name="Mulher")
    first = Theme.objects.create(slug="violencia", name="Violência")
    PropositionTheme.objects.create(proposition=proposition, theme=second, rank=2)
    PropositionTheme.objects.create(proposition=proposition, theme=first, rank=1)
    PropositionAnalysis.objects.create(proposition=proposition, theme_category="saude")
    request = RequestFactory().get("/admin/propositions/proposition/")
    request.user = get_user_model()(is_active=True, is_staff=True, is_superuser=True)
    model_admin = PropositionAdmin(Proposition, admin.site)

    row = model_admin.get_queryset(request).get(pk=proposition.pk)

    assert "ementa" in model_admin.list_display
    assert "ai_theme_category" in model_admin.list_display
    assert model_admin.relevance_terms(row) == "Violência, Mulher"
    assert model_admin.ai_theme_category(row) == "Saúde"


@pytest.mark.django_db
def test_delete_confirmation_does_not_load_large_payloads():
    proposition = Proposition.objects.create(
        house="camara",
        external_id=1,
        type_code="PL",
        number_label="PL 1/2026",
        number=1,
        year=2026,
        presented_at="2026-01-01",
        ementa="Ementa",
        full_text="texto integral",
        raw_payload={"source": "payload"},
    )
    PropositionEvent.objects.create(
        proposition=proposition,
        event_at="2026-01-01T00:00:00Z",
        description="Evento",
        raw_payload={"source": "payload"},
    )
    request = RequestFactory().post("/admin/propositions/proposition/")
    request.user = get_user_model()(is_active=True, is_staff=True, is_superuser=True)

    with CaptureQueriesContext(connection) as queries:
        _, model_count, _, _ = PropositionAdmin(Proposition, admin.site).get_deleted_objects(
            Proposition.objects.filter(pk=proposition.pk), request
        )

    sql = "\n".join(query["sql"] for query in queries.captured_queries)
    large_fields = {
        Proposition: ("ementa", "keywords", "full_text", "raw_payload"),
        PropositionEvent: ("description", "dispatch", "raw_payload"),
        PropositionAnalysis: ("theme_scores", "favorability_scores", "ai_summary"),
        PropositionContentVersion: ("text",),
        ClassificationRequest: ("input_text", "result"),
        PropositionAnnotation: ("comments",),
        PropositionEmbedding: ("embedding",),
    }
    for model, fields in large_fields.items():
        for field_name in fields:
            column = model._meta.get_field(field_name).column
            assert f'"{model._meta.db_table}"."{column}"' not in sql
    assert model_count == {
        Proposition._meta.verbose_name_plural: 1,
        PropositionEvent._meta.verbose_name_plural: 1,
    }
