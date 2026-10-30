from unittest.mock import Mock

import pytest

from apps.propositions.models import AssessmentOrganization, Proposition, PropositionAnnotation


@pytest.mark.django_db
def test_annotation_save_enqueues_site_deploy(
    monkeypatch, django_capture_on_commit_callbacks
):
    proposition = Proposition.objects.create(
        house="camara",
        external_id=1,
        type_code="PL",
        number_label="PL 1/2026",
        number=1,
        year=2026,
        presented_at="2026-01-01",
        ementa="Ementa",
        is_approved=True,
    )
    organization = AssessmentOrganization.objects.create(name="Organização")
    deploy = Mock()
    monkeypatch.setattr("apps.cms.tasks.enqueue_site_deploy", deploy)
    monkeypatch.setattr("apps.propositions.signals._enqueue", Mock())

    with django_capture_on_commit_callbacks(execute=True):
        PropositionAnnotation.objects.create(
            proposition=proposition,
            organization=organization,
            category="saude",
        )

    deploy.assert_called_once_with()
