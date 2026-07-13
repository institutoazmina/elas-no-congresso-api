"""Orquestração da coleta diária via Celery.

Substitui run.sh + Scrapy + cron externo. Agendado pelo Celery Beat (ver settings).

Fluxo:
  ingest_camara / ingest_senado  (1 por casa, rodam em paralelo)
    └─ lista a janela diária
       └─ filtra por tema (assert_theme) ANTES dos saltos caros
          └─ busca detalhe + autores só do que é relevante
             └─ upsert idempotente (update_or_create) no domínio relacional
                └─ classify_proposition.delay(id)  (ML desacoplado — hoje só loga)
"""

import logging
from datetime import date, timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.propositions.models import Proposition, PropositionAuthor, PropositionEvent
from apps.taxonomy.models import PropositionTheme, Theme

from .clients.camara import CamaraClient
from .clients.senado import SenadoClient
from .mappers import (
    enrich_camara_author,
    map_camara_event,
    map_camara_proposition,
    map_senado_event,
    map_senado_proposition,
    parse_camara_authors,
    parse_senado_authors,
    parse_senado_authors_from_autoria,
    pick_senado_full_text_url,
)
from .models import IngestionRun
from .resolvers import resolve_author
from .theme_assert import assert_theme

logger = logging.getLogger(__name__)


# ── persistência compartilhada ───────────────────────────────────────────────

def _persist(prop_kwargs: dict, event_kwargs: dict | None, authors: list[dict], temas: list[str]) -> int:
    """Upsert idempotente de uma proposição + evento + autores + temas.

    Retorna o pk da Proposition. Toda a escrita roda numa transação.
    """
    house = prop_kwargs["house"]
    external_id = prop_kwargs.pop("external_id")
    with transaction.atomic():
        prop, _ = Proposition.objects.update_or_create(
            house=house, external_id=external_id, defaults=prop_kwargs
        )

        if event_kwargs:
            PropositionEvent.objects.update_or_create(
                proposition=prop,
                event_at=event_kwargs.pop("event_at"),
                defaults=event_kwargs,
            )

        # Autores: substitui o conjunto a cada coleta (fonte da verdade é a API).
        prop.authors.all().delete()
        for a in authors:
            parl, inst = resolve_author(a, house)
            if not (parl or inst):
                continue
            party = None
            if a.get("party"):
                from apps.legislatures.models import Party

                sigla = a["party"].strip().upper()
                party, _ = Party.objects.get_or_create(
                    acronym=sigla, defaults={"name": sigla}
                )
            PropositionAuthor.objects.create(
                proposition=prop,
                parliamentarian=parl,
                institutional_author=inst,
                party=party,
                state_at_authorship=a.get("state"),
                order_index=a.get("order", 1),
            )

        # Temas detectados pelo regex de relevância.
        for rank, tema in enumerate(dict.fromkeys(t.strip() for t in temas if t), start=1):
            theme, _ = Theme.objects.get_or_create(
                slug=_slugify(tema), defaults={"name": tema.title()}
            )
            PropositionTheme.objects.update_or_create(
                proposition=prop, theme=theme, defaults={"rank": rank}
            )

    return prop.pk


def _slugify(value: str) -> str:
    import re
    import unicodedata

    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[\s_-]+", "-", value) or "tema"


def _daily_window() -> tuple[date, date]:
    """Janela ontem→amanhã, igual ao bot original (apanha fuso/atrasos)."""
    today = timezone.localdate()
    return today - timedelta(days=1), today + timedelta(days=1)


# ── Câmara ───────────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def ingest_camara(self):
    start, end = _daily_window()
    run = IngestionRun.objects.create(
        house="camara", window_start=start, window_end=end
    )
    try:
        with CamaraClient() as client:
            for summary in client.list_propositions(start, end):
                run.fetched_count += 1
                result = assert_theme(summary.get("ementa"))
                if not result["row_relevant"]:
                    continue
                run.relevant_count += 1
                try:
                    prop_id = int(summary["id"])
                    detail = client.fetch_detail(prop_id)
                    # Re-checa com ementa detalhada + keywords (mais sinal).
                    result = assert_theme(
                        summary.get("ementa"),
                        detail.get("ementaDetalhada"),
                        detail.get("keywords"),
                    )
                    if not result["row_relevant"]:  # pragma: no cover — defensivo
                        continue
                    authors = parse_camara_authors(client.fetch_authors(prop_id))
                    for author in authors:
                        if author["external_id"]:  # deputado → busca sexo/partido/UF
                            enrich_camara_author(author, client.fetch_deputy(author["external_id"]))
                    pk = _persist(
                        map_camara_proposition(summary, detail),
                        map_camara_event(detail),
                        authors,
                        result["temas"],
                    )
                    run.upserted_count += 1
                    classify_proposition.delay(pk)
                except Exception:
                    run.error_count += 1
                    logger.exception("Falha ao processar proposição Câmara %s", summary.get("id"))
        _finish(run, IngestionRun.Status.SUCCESS)
    except Exception as exc:
        _finish(run, IngestionRun.Status.FAILED, str(exc))
        raise self.retry(exc=exc) from exc
    return run.pk


# ── Senado ───────────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def ingest_senado(self):
    start, end = _daily_window()
    run = IngestionRun.objects.create(
        house="senado", window_start=start, window_end=end
    )
    try:
        with SenadoClient() as client:
            for summary in client.list_materias(end - timedelta(days=1)):
                run.fetched_count += 1
                result = assert_theme(summary.get("Ementa"))
                if not result["row_relevant"]:
                    continue
                run.relevant_count += 1
                try:
                    ident = summary.get("IdentificacaoMateria", {}) or {}
                    materia_id = int(ident.get("CodigoMateria") or summary["CodigoMateria"])
                    detail = client.fetch_detail(materia_id)
                    movements = client.fetch_movements(materia_id)
                    full_text_url = pick_senado_full_text_url(client.fetch_texts(materia_id))
                    # Autoria traz sexo/partido/UF; cai no texto livre se vazio.
                    authors = parse_senado_authors_from_autoria(
                        client.fetch_authors(materia_id)
                    ) or parse_senado_authors(detail, summary)
                    pk = _persist(
                        map_senado_proposition(summary, detail, full_text_url),
                        map_senado_event(movements),
                        authors,
                        result["temas"],
                    )
                    run.upserted_count += 1
                    classify_proposition.delay(pk)
                except Exception:
                    run.error_count += 1
                    logger.exception("Falha ao processar matéria Senado %s", summary)
        _finish(run, IngestionRun.Status.SUCCESS)
    except Exception as exc:
        _finish(run, IngestionRun.Status.FAILED, str(exc))
        raise self.retry(exc=exc) from exc
    return run.pk


def _finish(run: IngestionRun, status: str, error: str | None = None):
    run.status = status
    run.error_detail = error
    run.finished_at = timezone.now()
    run.save()
    logger.info(
        "Coleta %s %s: fetched=%d relevant=%d upserted=%d errors=%d",
        run.house, status, run.fetched_count, run.relevant_count,
        run.upserted_count, run.error_count,
    )


# ── classificação (ML) — TBD, hoje só loga ───────────────────────────────────

@shared_task
def classify_proposition(proposition_id: int):
    """Classificação (ML) — onde rodar o modelo está pendente (HF endpoint /
    fila dedicada / local). Por ora: prepara o inteiro teor (download + extração
    de texto do PDF) e apenas loga; a inferência em si é um stub.
    """
    prop = Proposition.objects.filter(pk=proposition_id).first()
    if not prop:
        logger.warning("[ML] proposição id=%s não encontrada", proposition_id)
        return

    full_text = None
    if prop.full_text_url:
        from .fulltext import extract_pdf_text

        full_text = extract_pdf_text(prop.full_text_url)
        if full_text:
            prop.full_text = full_text
            prop.save(update_fields=["full_text"])

    logger.info(
        "[ML pendente] classificar proposição id=%s %s — inteiro teor: %s chars",
        proposition_id,
        prop.number_label,
        len(full_text) if full_text else 0,
    )


# ── carga retroativa de anotações — JOB TEMPORÁRIO (remover após a carga) ─────

@shared_task(bind=True)
def backfill_annotations(self, reset: bool = True, start: int = 0, limit: int | None = None):
    """Carga retroativa das anotações humanas (one-shot, sequencial).

    Roda em processo no worker, gravando uma a uma (durável). Para retomar após
    queda, disparar de novo com ``start=<última linha>`` e ``reset=False``.
    """
    from scripts.load_annotations import run

    logger.info("[backfill] iniciando (reset=%s start=%s limit=%s)", reset, start, limit)
    stats = run(reset=reset, start=start, limit=limit)
    logger.info("[backfill] concluído: %s", stats)
    return stats
