"""Durable daily delta collection; document extraction and AI have separate queues."""

import logging
import re
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.propositions.activity import invalidate_activity_cache
from apps.propositions.models import IgnoredProposition, Proposition

from .content import register_document
from .mappers import (
    _parse_date,
    _parse_datetime,
    enrich_camara_author,
    map_camara_enactment,
    map_camara_event,
    map_camara_events,
    map_camara_proposition,
    map_senado_enactment,
    map_senado_process_events,
    map_senado_process_status,
    map_senado_proposition,
    parse_camara_authors,
    parse_senado_authors,
    parse_senado_authors_from_autoria,
    pick_senado_full_text_url,
)
from .models import IngestionCheckpoint, IngestionItem, IngestionRun
from .theme_assert import assert_theme

logger = logging.getLogger(__name__)


def enqueue_manual_links(identities):
    """Create durable, independently retryable runs for selected official IDs."""
    from .tasks import sync_daily_batch

    runs = []
    today = timezone.localdate()
    with transaction.atomic():
        for house in ("camara", "senado"):
            ids = list(
                dict.fromkeys(external_id for source, external_id in identities if source == house)
            )
            if not ids:
                continue
            run = IngestionRun.objects.create(
                house=house,
                kind="manual",
                window_start=today,
                window_end=today + timedelta(days=1),
                discovery_complete=True,
                fetched_count=len(ids),
            )
            IngestionItem.objects.bulk_create(
                [IngestionItem(run=run, external_id=external_id) for external_id in ids]
            )
            transaction.on_commit(lambda run_id=run.pk: sync_daily_batch.delay(run_id))
            runs.append(run)
    return runs


def begin_daily(house, client_factory):
    key = f"ingestion:discovery:{house}"
    if not cache.add(key, True, timeout=1800):
        return None
    try:
        return _begin_daily(house, client_factory)
    finally:
        cache.delete(key)


def _begin_daily(house, client_factory):
    from .tasks import sync_daily_batch

    with transaction.atomic():
        checkpoint, _ = IngestionCheckpoint.objects.select_for_update().get_or_create(house=house)
        run = checkpoint.active_run
        if run is None or run.status == run.Status.SUCCESS:
            since = (
                timezone.localdate(checkpoint.covered_until)
                if checkpoint.covered_until
                else timezone.localdate() - timedelta(days=14)
            )
            start = since - timedelta(days=2)
            run = IngestionRun.objects.create(
                house=house,
                window_start=start,
                window_end=timezone.localdate() + timedelta(days=1),
                checkpoint_until=timezone.now(),
            )
            checkpoint.active_run = run
            checkpoint.save(update_fields=["active_run", "updated_at"])
        elif run.status == run.Status.RUNNING and run.discovery_complete:
            transaction.on_commit(lambda: sync_daily_batch.delay(run.pk))
            return run.pk
        else:
            run.status = run.Status.RUNNING
            run.finished_at, run.error_detail = None, ""
            run.save(update_fields=["status", "finished_at", "error_detail"])
            run.items.filter(status=IngestionItem.Status.FAILED).update(
                status=IngestionItem.Status.PENDING, attempts=0
            )
    if not run.discovery_complete:
        try:
            with client_factory() as client:
                summaries = (
                    client.list_propositions(run.window_start, run.window_end - timedelta(days=1))
                    if house == "camara"
                    else client.list_materias(run.window_start)
                )
                pending = []
                for summary in summaries:
                    external_id = int(
                        summary["id"]
                        if house == "camara"
                        else summary["IdentificacaoMateria"]["CodigoMateria"]
                    )
                    pending.append(IngestionItem(run=run, external_id=external_id, summary=summary))
                    if len(pending) == 500:
                        IngestionItem.objects.bulk_create(pending, ignore_conflicts=True)
                        pending = []
                IngestionItem.objects.bulk_create(pending, ignore_conflicts=True)
            run.discovery_complete = True
            run.fetched_count = run.items.count()
            run.save(update_fields=["discovery_complete", "fetched_count"])
        except Exception as exc:
            run.status, run.error_detail = (
                run.Status.FAILED,
                f"Discovery failed ({type(exc).__name__}); checkpoint unchanged",
            )
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "error_detail", "finished_at"])
            return run.pk
    sync_daily_batch.delay(run.pk)
    return run.pk


def _documents(prop, client, events, *, verify=False, process_id=None, baseline=False):
    content_events = [
        e
        for e in events
        if re.search(
            r"substitut|reda[cç][aã]o|emenda|inteiro teor|texto integral",
            str(e.get("title", "")) + str(e.get("description", "")),
            re.I,
        )
    ]
    revision = str(content_events[-1].get("source_event_id")) if content_events else None
    register_document(
        prop.pk,
        "original",
        "original",
        prop.full_text_url,
        revision=revision,
        verify=verify,
        analyze_on_first=not baseline,
    )
    if prop.house == "camara":
        if not verify and not content_events:
            return
        for related in client.fetch_related(prop.external_id):
            kind = str(related.get("siglaTipo", "")).upper()
            if kind not in {"SBT", "RDF", "EMA", "EMC", "EMP", "EMS"}:
                continue
            detail = client.fetch_detail(int(related["id"]))
            if kind not in {"SBT", "RDF"} and not re.search(
                r"substitutiv|texto integral|reda[cç][aã]o integral", detail.get("ementa", ""), re.I
            ):
                continue
            register_document(
                prop.pk,
                f"camara:{related['id']}",
                "replacement",
                detail.get("urlInteiroTeor"),
                revision=detail.get("dataApresentacao", ""),
                source_date=_parse_datetime(detail.get("dataApresentacao")),
                verify=verify,
                analyze_on_first=not baseline,
            )
    elif process_id:
        for doc in client.fetch_documents(process_id):
            kind = str(doc.get("siglaTipo", "")).upper()
            description = str(doc.get("descricaoTipo", "")).lower()
            if kind not in {
                "SBT",
                "SUBSTITUTIVO",
                "RDF",
                "AVULSO_REDACAO",
                "EMD",
                "EMENDA",
                "EMENDA_LEGADO",
                "EMA",
                "EMC",
                "EMP",
            } and not any(
                t in description for t in ("substitutivo", "redação final", "emenda ao projeto")
            ):
                continue
            if any(t in description for t in ("parecer", "relatório", "requerimento")):
                continue
            if kind not in {"SBT", "SUBSTITUTIVO", "RDF", "AVULSO_REDACAO"} and not re.search(
                r"substitutiv|texto integral|reda[cç][aã]o integral",
                str(doc.get("descricao", "")),
                re.I,
            ):
                continue
            register_document(
                prop.pk,
                f"senado:{doc['id']}",
                "replacement",
                doc.get("urlDocumento"),
                revision=doc.get("dataDocumento", ""),
                source_date=_parse_datetime(doc.get("dataDocumento")),
                verify=verify,
                analyze_on_first=not baseline,
            )


def _discovery_relevance(fields, *ementas):
    """Use ementas alone for missing links or interactive document verification."""
    relevance = assert_theme(fields.get("ementa"), *ementas)
    if relevance["row_relevant"]:
        return relevance
    url = fields.get("full_text_url")
    if not url:
        logger.info("Relevance checked using ementa only: document link unavailable")
        return relevance
    from urllib.parse import urlparse

    from .clients.base import throttle_source
    from .fulltext import (
        DocumentSecurityChallengeError,
        UnsupportedDocumentError,
        extract_pdf_text,
    )

    throttle_source(urlparse(url).netloc)
    try:
        text = extract_pdf_text(
            url,
            raise_on_challenge=True,
            raise_on_unsupported=True,
        )
    except (DocumentSecurityChallengeError, UnsupportedDocumentError) as exc:
        logger.info("Relevance checked using ementa only: %s (%s)", exc, url)
        return relevance
    if not text:
        raise ValueError("Full text extraction failed for relevance check")
    fields["full_text"] = text
    return assert_theme(fields.get("ementa"), *ementas, text)


def sync_item(item, client, *, reconcile=False):
    from .tasks import _enactment_fields, _persist

    if IgnoredProposition.objects.filter(
        house=item.run.house, external_id=item.external_id
    ).exists():
        return None

    existing = Proposition.objects.filter(
        house=item.run.house, external_id=item.external_id
    ).first()
    manual = item.run.kind == "manual"
    summary = item.summary
    relevance = {"row_relevant": False, "temas": []}
    authors, process_id = None, None
    if item.run.house == "camara":
        detail = client.fetch_detail(item.external_id)
        if not detail:
            raise ValueError("Empty Camara detail")
        fields = map_camara_proposition({**summary, "id": item.external_id}, detail)
        if detail.get("ementa"):
            fields["ementa"] = detail["ementa"]
        if not existing and not manual:
            relevance = _discovery_relevance(
                fields, summary.get("ementa"), detail.get("ementaDetalhada")
            )
            if not relevance["row_relevant"]:
                return None
        events = (
            client.fetch_tramitations(item.external_id, start=item.run.window_start)
            if existing and existing.reconciled_at and not reconcile
            else client.fetch_tramitations(item.external_id)
        )
        if existing:
            fields = {
                key: value
                for key, value in fields.items()
                if key
                in {
                    "house",
                    "external_id",
                    "ementa",
                    "keywords",
                    "full_text_url",
                    "current_status",
                    "current_status_code",
                    "regime",
                    "scope",
                    "appreciation_mode",
                    "raw_payload",
                }
            }
        enactment = map_camara_enactment(detail, events)
        if enactment or reconcile or not existing:
            fields.update(_enactment_fields(enactment))
        mapped_events = map_camara_events(events)
        if not mapped_events:
            fallback = map_camara_event(detail)
            mapped_events = [fallback] if fallback else []
        if reconcile or not existing or not existing.authors.exists():
            authors = parse_camara_authors(client.fetch_authors(item.external_id))
            for author in authors:
                if author["external_id"]:
                    enrich_camara_author(author, client.fetch_deputy(author["external_id"]))
    else:
        if manual:
            found = client.find_process(item.external_id)
            if not found:
                raise ValueError("Senate process mapping missing")
            summary = {
                "_process_summary": found,
                "Ementa": found.get("ementa", ""),
                "IdentificacaoMateria": {
                    "CodigoMateria": item.external_id,
                    "IdentificacaoProcesso": found["id"],
                },
            }
        ident = summary.get("IdentificacaoMateria", {})
        process_id = ident.get("IdentificacaoProcesso") or (
            (existing.raw_payload or {}).get("_senado_process_id") if existing else None
        )
        if not process_id and existing:
            found = client.find_process(existing.external_id)
            process_id = found["id"] if found else None
        if not process_id:
            raise ValueError("Senate process mapping missing")
        process = client.fetch_process(int(process_id))
        if not process:
            raise ValueError("Empty Senate process")
        source_document = process.get("documento", {}) or {}
        mapped_events = map_senado_process_events(process)
        if existing:
            fields = {
                "house": "senado",
                "external_id": existing.external_id,
                "raw_payload": {
                    **(existing.raw_payload or {}),
                    "_senado_process_id": int(process_id),
                },
            }
            ementa = (process.get("conteudo", {}) or {}).get("ementa") or process.get("ementa")
            if ementa:
                fields["ementa"] = ementa
            if source_document.get("url") or process.get("urlDocumento"):
                fields["full_text_url"] = source_document.get("url") or process.get("urlDocumento")
        else:
            if "_process_summary" in summary:
                data = summary["_process_summary"]
                label = data.get("identificacao", "")
                match = re.search(r"([A-Za-z]+)\s*0*(\d+)\s*/\s*(\d{4})", label)
                if not match:
                    raise ValueError("Unrecognized Senate identity")
                type_code, number, year = match.groups()
                fields = {
                    "house": "senado",
                    "external_id": item.external_id,
                    "type_code": type_code,
                    "number": int(number),
                    "year": int(year),
                    "number_label": label,
                    "presented_at": _parse_date(data.get("dataApresentacao")),
                    "ementa": data.get("ementa", ""),
                    "full_text_url": source_document.get("url")
                    or process.get("urlDocumento")
                    or data.get("urlDocumento"),
                    "tramitation_url": f"https://www25.senado.leg.br/web/atividade/materias/-/materia/{item.external_id}"
                    if item.external_id > 0
                    else f"https://legis.senado.leg.br/dadosabertos/processo/{process_id}",
                    "raw_payload": {"_senado_process_id": int(process_id)},
                }
            else:
                detail = client.fetch_detail(item.external_id)
                fields = map_senado_proposition(
                    summary, detail, pick_senado_full_text_url(client.fetch_texts(item.external_id))
                )
            process_ementa = (process.get("conteudo", {}) or {}).get("ementa") or process.get(
                "ementa"
            )
            if process_ementa:
                fields["ementa"] = process_ementa
            if not manual:
                relevance = _discovery_relevance(fields, summary.get("Ementa"))
                if not relevance["row_relevant"]:
                    return None
            authors = (
                parse_senado_authors_from_autoria(client.fetch_authors(item.external_id))
                if item.external_id > 0
                else []
            )
            if not authors and "_process_summary" not in summary:
                authors = parse_senado_authors(detail, summary)
        if existing and (reconcile or not existing.authors.exists()) and item.external_id > 0:
            authors = parse_senado_authors_from_autoria(client.fetch_authors(item.external_id))
        fields.update(map_senado_process_status(process))
        fields.update(_enactment_fields(map_senado_enactment(process)))
    if manual:
        relevance = assert_theme(fields.get("ementa"))
    pk = _persist(
        fields,
        mapped_events,
        authors,
        relevance["temas"] if not existing else [],
        approve=manual,
    )
    prop = Proposition.objects.get(pk=pk)
    recent_events = [
        e for e in mapped_events if timezone.localdate(e["event_at"]) >= item.run.window_start
    ]
    _documents(
        prop,
        client,
        recent_events,
        verify=reconcile,
        process_id=process_id,
        baseline=bool(existing and not existing.reconciled_at and not manual),
    )
    if reconcile or existing is None:
        Proposition.objects.filter(pk=pk).update(reconciled_at=timezone.now())
    return prop


def finish_run(run):
    run.processed_count = run.items.filter(status=IngestionItem.Status.SUCCEEDED).count()
    run.upserted_count = run.relevant_count = run.processed_count
    run.skipped_count = run.items.filter(status=IngestionItem.Status.SKIPPED).count()
    run.error_count = run.items.filter(status=IngestionItem.Status.FAILED).count()
    if (
        run.discovery_complete
        and not run.items.filter(status=IngestionItem.Status.PENDING).exists()
    ):
        run.status = run.Status.FAILED if run.error_count else run.Status.SUCCESS
        run.finished_at = timezone.now()
        if run.status == run.Status.SUCCESS and run.kind == "daily":
            with transaction.atomic():
                checkpoint = IngestionCheckpoint.objects.select_for_update().get(house=run.house)
                checkpoint.covered_since = checkpoint.covered_since or run.window_start
                checkpoint.covered_until = max(
                    checkpoint.covered_until or run.checkpoint_until, run.checkpoint_until
                )
                checkpoint.save(update_fields=["covered_since", "covered_until", "updated_at"])
    if (
        run.status == run.Status.SUCCESS
        and run.kind == "reconcile"
        and not Proposition.objects.filter(house=run.house, reconciled_at__isnull=True).exists()
    ):
        IngestionCheckpoint.objects.filter(house=run.house).update(baseline_complete=True)
    run.save()
    if run.kind in {"daily", "manual"} and run.processed_count:
        from apps.cms.tasks import enqueue_site_deploy

        enqueue_site_deploy()
    logger.info(
        "Daily ingestion %s/%s: processed=%s skipped=%s failed=%s status=%s",
        run.house,
        run.pk,
        run.processed_count,
        run.skipped_count,
        run.error_count,
        run.status,
    )


def process_batch(run_id, client_factory):
    run = IngestionRun.objects.get(pk=run_id)
    if run.status != run.Status.RUNNING or not run.discovery_complete:
        return
    changed = []
    with client_factory() as client:
        for item in run.items.filter(
            Q(status=IngestionItem.Status.PENDING)
            | Q(status=IngestionItem.Status.FAILED, attempts__lt=3)
        ).order_by("pk")[: settings.INGESTION_BATCH_SIZE]:
            item.attempts += 1
            try:
                prop = sync_item(item, client, reconcile=run.kind in {"reconcile", "manual"})
                item.status = item.Status.SUCCEEDED if prop else item.Status.SKIPPED
                item.error = ""
                if prop:
                    changed.append(prop)
            except Exception as exc:
                item.status, item.error = (
                    item.Status.FAILED,
                    f"Source update failed ({type(exc).__name__})",
                )
            item.processed_at = timezone.now()
            item.save(update_fields=["status", "error", "processed_at", "attempts"])
    if changed:
        invalidate_activity_cache(changed)
    if run.items.filter(
        Q(status=IngestionItem.Status.PENDING)
        | Q(status=IngestionItem.Status.FAILED, attempts__lt=3)
    ).exists():
        return True
    else:
        finish_run(run)
