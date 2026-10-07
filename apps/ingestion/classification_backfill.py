"""Fill evaluation gaps using stored text and the durable classification queue."""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone

from apps.core.enums import PropositionCategory
from apps.propositions.models import ClassificationRequest, Proposition, PropositionAnnotation

from .content import configuration_hash, register_fallback, request_analysis


def missing_evaluations():
    annotations = PropositionAnnotation.objects.filter(proposition_id=OuterRef("pk"))
    return (
        Proposition.objects.filter(~Exists(annotations))
        .exclude(analysis__expert_id__isnull=False)
        .exclude(Q(analysis__expert_opinion__isnull=False) & ~Q(analysis__expert_opinion=""))
        .exclude(
            analysis__theme_category__in=PropositionCategory.values,
            analysis__classification__in=[0, 1],
        )
    )


def candidates(*, retry_failed=False):
    if retry_failed:
        stale = timezone.now() - timedelta(minutes=90)
        blocked = Q(status="pending") | Q(status="running", attempted_at__gte=stale)
    else:
        blocked = Q(status__in=["pending", "running", "failed"])
    outstanding = ClassificationRequest.objects.filter(
        blocked,
        proposition_id=OuterRef("pk"),
        content_hash=OuterRef("current_content__text_hash"),
        configuration_hash=configuration_hash(),
    )
    return missing_evaluations().filter(~Exists(outstanding)).order_by("pk")


def backfill_status():
    missing = missing_evaluations()
    requests = ClassificationRequest.objects.filter(proposition_id__in=missing.values("pk"))
    return {
        "total": Proposition.objects.count(),
        "missing_evaluation": missing.count(),
        "ready_to_queue": candidates().count(),
        "request_states_for_missing": dict(
            requests.values("status").annotate(count=Count("pk")).values_list("status", "count")
        ),
        "quiteria_enabled": settings.QUITERIA_ENABLED,
    }


def prepare_missing_evaluations(*, limit=0, retry_failed=False):
    if not settings.QUITERIA_ENABLED:
        raise ValueError("QuitérIA está desativada; nenhum pedido foi criado.")
    if limit < 0:
        raise ValueError("O limite deve ser zero (todos) ou positivo.")
    targets = candidates(retry_failed=retry_failed).values_list("pk", flat=True)
    if limit:
        targets = targets[:limit]
    stats = {"prepared": 0, "reused": 0, "retried": 0, "skipped": 0}
    for pk in targets.iterator(chunk_size=200):
        with transaction.atomic():
            prop = Proposition.objects.select_for_update(of=("self",)).get(pk=pk)
            if not missing_evaluations().filter(pk=pk).exists():
                stats["skipped"] += 1
                continue
            if not prop.current_content_id:
                register_fallback(pk, analyze=False)
                prop.refresh_from_db()
            # Existing selected substantive text takes precedence over the original.
            req = request_analysis(prop, prop.current_content, only_if_unevaluated=True)
            if retry_failed and req.status in {req.Status.FAILED, req.Status.RUNNING}:
                if (
                    req.status == req.Status.RUNNING
                    and req.attempted_at
                    and req.attempted_at > timezone.now() - timedelta(minutes=90)
                ):
                    stats["skipped"] += 1
                    continue
                req.status, req.attempts, req.error = req.Status.PENDING, 0, ""
                req.only_if_unevaluated = True
                req.save(update_fields=["status", "attempts", "error", "only_if_unevaluated"])
                from .tasks import run_classification_request

                transaction.on_commit(
                    lambda request_id=req.pk: run_classification_request.delay(request_id)
                )
                stats["retried"] += 1
            elif req.status == req.Status.SUCCEEDED:
                stats["reused"] += 1
            else:
                stats["prepared"] += 1
    return stats
