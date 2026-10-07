from datetime import date, timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.ingestion import content, tasks
from apps.ingestion.classification_backfill import (
    backfill_status,
    missing_evaluations,
    prepare_missing_evaluations,
)
from apps.propositions.models import (
    AssessmentOrganization,
    ClassificationRequest,
    Proposition,
    PropositionAnalysis,
    PropositionAnnotation,
    PropositionContentVersion,
)

pytestmark = pytest.mark.django_db


def proposal(number=1, **kwargs):
    return Proposition.objects.create(
        house="camara",
        external_id=number,
        type_code="PL",
        number=number,
        year=2026,
        number_label=f"PL {number}/2026",
        presented_at=date(2026, 10, 1),
        ementa="Proteção das mulheres",
        **kwargs,
    )


def human_review(prop):
    org, _ = AssessmentOrganization.objects.get_or_create(name="Avaliadora")
    return PropositionAnnotation.objects.create(
        proposition=prop,
        organization=org,
        category="saude",
        is_favorable=True,
    )


@pytest.fixture
def ai(monkeypatch, settings):
    settings.QUITERIA_ENABLED = True
    queued = Mock()
    monkeypatch.setattr(tasks.run_classification_request, "delay", queued)
    alerts = Mock()
    monkeypatch.setattr("apps.subscriptions.tasks.match_and_notify.delay", alerts)
    model = Mock()
    model.classify.return_value = SimpleNamespace(
        theme_category="saude",
        theme_confidence=0.9,
        theme_scores={"LABEL_7": 0.9},
        favorability_probability=0.3,
        favorability_scores={"LABEL_1": 0.3},
    )
    monkeypatch.setattr("apps.propositions.quiteria.get_classifier", lambda: model)
    return model, queued, alerts


def test_selection_excludes_humans_and_complete_ai_but_includes_partial_results():
    human_review(proposal(1))
    PropositionAnalysis.objects.create(proposition=proposal(2), expert_opinion="Revisada")
    PropositionAnalysis.objects.create(proposition=proposal(3), expert_id=42)
    PropositionAnalysis.objects.create(
        proposition=proposal(4), theme_category="saude", classification=0
    )
    partial = proposal(5)
    PropositionAnalysis.objects.create(proposition=partial, theme_category="saude")
    absent = proposal(6)
    assert set(missing_evaluations().values_list("pk", flat=True)) == {partial.pk, absent.pk}


def test_queue_is_idempotent_and_inference_fills_both_fields_without_alerts(
    ai, django_capture_on_commit_callbacks
):
    prop = proposal(full_text="Texto integral armazenado", is_active=False)
    with django_capture_on_commit_callbacks(execute=True):
        assert prepare_missing_evaluations()["prepared"] == 1
        assert prepare_missing_evaluations()["prepared"] == 0
    req = ClassificationRequest.objects.get()
    assert req.only_if_unevaluated
    assert "Texto integral armazenado" in req.input_text
    assert ai[1].call_count == 1
    with django_capture_on_commit_callbacks(execute=True):
        content.run_analysis(req.pk)
    prop.refresh_from_db()
    assert prop.analysis.theme_category == "saude"
    assert prop.analysis.classification == 1
    assert prop.analysis.analysis_status == "succeeded"
    assert not prop.is_approved
    assert backfill_status()["missing_evaluation"] == 0
    ai[2].assert_not_called()


def test_selected_substitutivo_is_used_without_document_download(ai):
    prop = proposal(full_text="Texto original")
    version = PropositionContentVersion.objects.create(
        proposition=prop,
        text="Texto do substitutivo",
        text_hash=content.text_digest("Texto do substitutivo"),
    )
    prop.current_content = version
    prop.save(update_fields=["current_content"])
    prepare_missing_evaluations()
    req = ClassificationRequest.objects.get()
    assert "Texto do substitutivo" in req.input_text
    assert req.content_version_id == version.pk
    assert not prop.documents.exists()


def test_human_review_while_queued_skips_inference(ai):
    prop = proposal()
    prepare_missing_evaluations()
    human_review(prop)
    req = ClassificationRequest.objects.get()
    content.run_analysis(req.pk)
    req.refresh_from_db()
    assert req.status == "superseded"
    ai[0].classify.assert_not_called()
    assert not PropositionAnalysis.objects.filter(proposition=prop).exists()


def test_human_review_during_inference_prevents_applying_ai(ai):
    prop = proposal()
    prepare_missing_evaluations()
    prediction = ai[0].classify.return_value
    ai[0].classify.side_effect = lambda _: (human_review(prop), prediction)[1]
    req = ClassificationRequest.objects.get()
    content.run_analysis(req.pk)
    req.refresh_from_db()
    assert req.status == "superseded"
    assert not PropositionAnalysis.objects.filter(proposition=prop).exists()


def test_recovery_is_bounded_and_manual_retry_resets_exhausted_failure(
    ai, django_capture_on_commit_callbacks
):
    proposal()
    prepare_missing_evaluations()
    req = ClassificationRequest.objects.get()
    req.status, req.attempts = "failed", 3
    req.save(update_fields=["status", "attempts"])
    assert prepare_missing_evaluations()["prepared"] == 0
    ai[1].reset_mock()
    with django_capture_on_commit_callbacks(execute=True):
        assert prepare_missing_evaluations(retry_failed=True)["retried"] == 1
    req.refresh_from_db()
    assert req.status == "pending"
    assert req.attempts == 0
    ai[1].assert_called_once_with(req.pk)


def test_cached_result_is_reused_after_analysis_removed(ai):
    prop = proposal()
    prepare_missing_evaluations()
    content.run_analysis(ClassificationRequest.objects.get().pk)
    PropositionAnalysis.objects.filter(proposition=prop).delete()
    assert prepare_missing_evaluations()["reused"] == 1
    assert ai[0].classify.call_count == 1
    assert not missing_evaluations().exists()


def test_retry_recovers_exhausted_abandoned_worker_but_not_live_work(ai):
    proposal()
    prepare_missing_evaluations()
    req = ClassificationRequest.objects.get()
    req.status, req.attempts, req.attempted_at = "running", 3, timezone.now()
    req.save(update_fields=["status", "attempts", "attempted_at"])
    assert prepare_missing_evaluations(retry_failed=True)["retried"] == 0
    req.attempted_at -= timedelta(hours=2)
    req.save(update_fields=["attempted_at"])
    assert prepare_missing_evaluations(retry_failed=True)["retried"] == 1
    req.refresh_from_db()
    assert req.status == "pending"
    assert req.attempts == 0


def test_reactivated_request_adopts_backfill_policy(ai, django_capture_on_commit_callbacks):
    prop = proposal()
    content.register_fallback(prop.pk, analyze=True)
    req = ClassificationRequest.objects.get()
    assert not req.only_if_unevaluated
    req.status = "superseded"
    req.save(update_fields=["status"])
    with django_capture_on_commit_callbacks(execute=True):
        prepare_missing_evaluations()
        content.run_analysis(req.pk)
    req.refresh_from_db()
    assert req.only_if_unevaluated
    assert req.status == "succeeded"
    ai[2].assert_not_called()


def test_preview_and_status_are_read_only_and_limit_is_respected(ai):
    proposal(1)
    proposal(2)
    output = StringIO()
    call_command("classification_backfill", mode="preview", stdout=output)
    assert '"missing_evaluation": 2' in output.getvalue()
    assert not ClassificationRequest.objects.exists()
    assert not PropositionContentVersion.objects.exists()
    prepare_missing_evaluations(limit=1)
    assert backfill_status()["ready_to_queue"] == 1
    assert ClassificationRequest.objects.count() == 1


def test_disabled_model_cannot_prepare_work(settings):
    settings.QUITERIA_ENABLED = False
    proposal()
    with pytest.raises(ValueError, match="desativada"):
        prepare_missing_evaluations()
    assert not ClassificationRequest.objects.exists()
