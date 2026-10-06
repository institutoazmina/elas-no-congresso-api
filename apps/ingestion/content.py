"""Version substantive text independently from legislative status and metadata."""

import hashlib
import json
from datetime import timedelta
from types import SimpleNamespace

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.propositions.models import (
    ClassificationRequest,
    Proposition,
    PropositionAnalysis,
    PropositionContentVersion,
    PropositionDocument,
)
from apps.propositions.quiteria import build_input, format_markdown


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def text_digest(text):
    return digest(" ".join(format_markdown(text).split()))


def configuration_hash():
    return digest(
        json.dumps(
            [
                settings.QUITERIA_MODEL_ID,
                settings.QUITERIA_MODEL_REVISION,
                settings.QUITERIA_FAVORABILITY_THRESHOLD,
                "quiteria-input-v1",
            ]
        )
    )


def request_analysis(prop, version):
    """Caller holds the proposition lock; metadata-only changes never call this."""
    if not settings.QUITERIA_ENABLED:
        return None
    input_text = build_input(
        SimpleNamespace(
            authors=prop.authors,
            full_text=version.text,
            ementa=prop.ementa,
        )
    )
    request, created = ClassificationRequest.objects.get_or_create(
        proposition=prop,
        content_hash=version.text_hash,
        configuration_hash=configuration_hash(),
        defaults={
            "content_version": version,
            "input_text": input_text,
            "input_hash": digest(input_text),
            "model_id": settings.QUITERIA_MODEL_ID,
            "model_revision": settings.QUITERIA_MODEL_REVISION,
            "threshold": settings.QUITERIA_FAVORABILITY_THRESHOLD,
        },
    )
    if not created and request.status == request.Status.SUCCEEDED and request.result:
        # Reverting to previously analyzed text reuses its result without model inference.
        PropositionAnalysis.objects.update_or_create(
            proposition=prop,
            defaults={
                **request.result,
                "content_version": version,
                "input_hash": request.input_hash,
                "model_id": request.model_id,
                "model_revision": request.model_revision,
                "analysis_status": PropositionAnalysis.Status.SUCCEEDED,
                "analysis_error": None,
                "completed_at": request.completed_at,
            },
        )
    if not created and request.status == request.Status.SUPERSEDED and not request.result:
        request.status, request.attempts = request.Status.PENDING, 0
        request.save(update_fields=["status", "attempts"])
        created = True
    if created:
        from .tasks import run_classification_request

        transaction.on_commit(lambda: run_classification_request.delay(request.pk))
    return request


def select_content(prop, version, *, analyze=True):
    if prop.current_content_id:
        current = prop.current_content
        if current.document_id and version.document_id:
            old_doc, new_doc = current.document, version.document
            if old_doc.role == "replacement" and new_doc.role == "original":
                return
            if (
                current.source_date
                and version.source_date
                and version.source_date < current.source_date
            ):
                return
        if current.text_hash == version.text_hash:
            if prop.current_content_id != version.pk:
                prop.current_content = version
                prop.save(update_fields=["current_content"])
                PropositionAnalysis.objects.filter(
                    proposition=prop, content_version=current
                ).update(content_version=version)
            return
    prop.current_content = version
    prop.save(update_fields=["current_content"])
    if analyze:
        request_analysis(prop, version)


def register_fallback(proposition_id, *, analyze):
    with transaction.atomic():
        prop = Proposition.objects.select_for_update(of=("self",)).get(pk=proposition_id)
        if prop.current_content_id and prop.current_content.document_id:
            return
        text = prop.full_text or prop.ementa
        version, _ = PropositionContentVersion.objects.get_or_create(
            proposition=prop,
            document=None,
            text_hash=text_digest(text),
            defaults={"text": text, "extraction_version": "stored-text-v1"},
        )
        # A legacy row without a known content baseline must not trigger a mass backfill.
        select_content(prop, version, analyze=analyze)


def register_document(
    proposition_id,
    source_key,
    role,
    url,
    *,
    revision=None,
    source_date=None,
    verify=False,
    analyze_on_first=True,
):
    if not url:
        return None
    source_revision = digest(json.dumps([url, revision or "", role]))
    with transaction.atomic():
        doc, created = PropositionDocument.objects.select_for_update(of=("self",)).get_or_create(
            proposition_id=proposition_id,
            source_key=str(source_key)[:128],
            defaults={
                "role": role,
                "url": url,
                "source_revision": source_revision,
                "source_date": source_date,
                "analyze_on_first": analyze_on_first,
            },
        )
        if not created and revision is None and doc.url == url and doc.role == role:
            source_revision = doc.source_revision
        changed = created or doc.source_revision != source_revision
        if changed or verify:
            if doc.url != url:
                doc.etag, doc.last_modified = "", ""
            doc.role, doc.url = role, url
            doc.source_revision, doc.source_date = source_revision, source_date
            doc.status, doc.attempts, doc.error = doc.Status.PENDING, 0, ""
            doc.save()
            from .tasks import check_proposition_document

            transaction.on_commit(lambda: check_proposition_document.delay(doc.pk))
    return doc


def check_document(document_id):
    with transaction.atomic():
        doc = PropositionDocument.objects.select_for_update(of=("self",)).get(pk=document_id)
        if doc.status == doc.Status.READY:
            return
        if (
            doc.status == doc.Status.FETCHING
            and doc.attempted_at
            and doc.attempted_at > timezone.now() - timedelta(minutes=90)
        ):
            return
        revision = doc.source_revision
        doc.status, doc.attempted_at = doc.Status.FETCHING, timezone.now()
        doc.attempts += 1
        doc.save(update_fields=["status", "attempted_at", "attempts"])
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; ElasNoCongresso/1.0)"}
        if doc.etag:
            headers["If-None-Match"] = doc.etag
        if doc.last_modified:
            headers["If-Modified-Since"] = doc.last_modified
        from urllib.parse import urlparse

        from .clients.base import throttle_source

        throttle_source(urlparse(doc.url).netloc)
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            response = client.get(doc.url, headers=headers)
        previous = doc.versions.order_by("-created_at", "-pk").first()
        if response.status_code == 304:
            if previous is None:
                raise ValueError("304 without stored text")
            text, bytes_hash = previous.text, doc.bytes_hash
        else:
            response.raise_for_status()
            if len(response.content) > 20 * 1024 * 1024:
                raise ValueError("Document exceeds extraction limit")
            bytes_hash = hashlib.sha256(response.content).hexdigest()
            if previous and bytes_hash == doc.bytes_hash:
                text = previous.text
            else:
                from .fulltext import _extract

                text = _extract(response.content, doc.url)
                if not text:
                    raise ValueError("Empty document extraction")
        with transaction.atomic():
            prop = Proposition.objects.select_for_update(of=("self",)).get(pk=doc.proposition_id)
            latest = PropositionDocument.objects.select_for_update(of=("self",)).get(pk=doc.pk)
            if latest.source_revision != revision:
                return  # A newer durable pending revision will be picked up separately.
            version, _ = PropositionContentVersion.objects.get_or_create(
                proposition=prop,
                document=latest,
                text_hash=text_digest(text),
                source_revision=revision,
                defaults={
                    "text": text,
                    "source_url": latest.url,
                    "source_date": latest.source_date,
                },
            )
            latest.status, latest.checked_revision = latest.Status.READY, revision
            latest.checked_at, latest.bytes_hash, latest.error = timezone.now(), bytes_hash, ""
            latest.etag = response.headers.get("ETag", latest.etag)
            latest.last_modified = response.headers.get("Last-Modified", latest.last_modified)
            latest.save()
            if latest.role == "original" and prop.full_text != text:
                prop.full_text = text
                prop.save(update_fields=["full_text"])
            select_content(prop, version, analyze=latest.analyze_on_first or previous is not None)
    except Exception as exc:
        PropositionDocument.objects.filter(pk=doc.pk, source_revision=revision).update(
            status=doc.Status.FAILED,
            error=f"Document verification failed ({type(exc).__name__})",
        )
        return False
    return True


def run_analysis(request_id):
    with transaction.atomic():
        req = ClassificationRequest.objects.select_for_update(of=("self",)).get(pk=request_id)
        if req.status in {req.Status.SUCCEEDED, req.Status.SUPERSEDED}:
            return
        if (
            req.status == req.Status.RUNNING
            and req.attempted_at
            and req.attempted_at > timezone.now() - timedelta(minutes=90)
        ):
            return
        prop = Proposition.objects.select_related("current_content").get(pk=req.proposition_id)
        if not prop.current_content_id or prop.current_content.text_hash != req.content_hash:
            req.status = req.Status.SUPERSEDED
            req.save(update_fields=["status"])
            return
        if not settings.QUITERIA_ENABLED:
            return
        if req.configuration_hash != configuration_hash():
            req.status, req.error = (
                req.Status.SUPERSEDED,
                "Model configuration changed; explicit reclassification required",
            )
            req.save(update_fields=["status", "error"])
            return
        req.status, req.attempted_at = req.Status.RUNNING, timezone.now()
        req.attempts += 1
        req.save(update_fields=["status", "attempted_at", "attempts"])
    try:
        from apps.propositions.quiteria import get_classifier

        prediction = get_classifier().classify(req.input_text)
        result = {
            "theme_category": prediction.theme_category,
            "theme_confidence": prediction.theme_confidence,
            "theme_scores": prediction.theme_scores,
            "classification": int(prediction.favorability_probability >= req.threshold),
            "classification_probability": prediction.favorability_probability,
            "favorability_scores": prediction.favorability_scores,
        }
        with transaction.atomic():
            prop = Proposition.objects.select_for_update(of=("self",)).get(pk=req.proposition_id)
            req.result, req.completed_at = result, timezone.now()
            if (
                not prop.current_content_id
                or prop.current_content.text_hash != req.content_hash
                or req.configuration_hash != configuration_hash()
            ):
                req.status = req.Status.SUPERSEDED
            else:
                req.status = req.Status.SUCCEEDED
                PropositionAnalysis.objects.update_or_create(
                    proposition=prop,
                    defaults={
                        **result,
                        "content_version": prop.current_content,
                        "input_hash": req.input_hash,
                        "model_id": req.model_id,
                        "model_revision": req.model_revision,
                        "analysis_status": PropositionAnalysis.Status.SUCCEEDED,
                        "analysis_error": None,
                        "completed_at": req.completed_at,
                    },
                )
                from apps.subscriptions.tasks import match_and_notify

                transaction.on_commit(lambda: match_and_notify.delay(prop.pk))
            req.error = ""
            req.save(update_fields=["result", "completed_at", "status", "error"])
    except Exception as exc:
        ClassificationRequest.objects.filter(pk=req.pk).update(
            status=req.Status.FAILED,
            error=f"Classification failed ({type(exc).__name__})",
        )
