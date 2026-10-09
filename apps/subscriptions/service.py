"""Subscription matching service (adapted from POC4 for Django)."""

from __future__ import annotations

import json

from django.db import connection
from django.utils import timezone

from .compiler import ast_to_tsquery, document_to_tsvector_tokens
from .document_builder import build_document
from .reference_matcher import matches as reference_matches


def register_subscriptions(email: str, alerts: list[dict]) -> list[int]:
    """Grava um registro por frequência escolhida. Semanal e diário têm filtros
    diferentes, então são linhas diferentes — mas do mesmo e-mail, confirmadas
    de uma vez só."""
    from .models import Subscription

    # Reinscrever é *substituir*: quem volta ao modal está reconfigurando o que
    # recebe, não somando uma segunda inscrição no mesmo endereço. A troca só
    # acontece na confirmação; até lá, apenas pedidos anteriores ainda não
    # confirmados são descartados e as inscrições confirmadas seguem valendo.
    Subscription.objects.filter(email=email, confirmed_at__isnull=True).delete()

    accepted_at = timezone.now()
    created = []
    for alert in alerts:
        tsq_str, needs_reval = ast_to_tsquery(alert["ast"])
        sub = Subscription.objects.create(
            email=email,
            frequency=alert["frequency"],
            ast=alert["ast"],
            query=tsq_str,
            needs_revalidation=needs_reval,
            is_active=False,
            accepted_terms_at=accepted_at,
        )
        # Store compiled tsquery in DB as text; matching done via raw SQL cast
        created.append(sub.pk)
    return created


def confirm_subscriptions(token: str) -> bool:
    """Ativa o pedido pendente do endereço e substitui as inscrições anteriores.

    Só confirma pedidos nunca confirmados e dentro do prazo, então um link
    antigo não reativa quem cancelou. O histórico de entregas das inscrições
    substituídas passa para a nova, para que proposições já enviadas não se
    repitam.
    """
    from datetime import timedelta

    from django.conf import settings
    from django.db import transaction

    from .models import AlertDelivery, Subscription

    expires_after = timezone.now() - timedelta(hours=settings.SUBSCRIPTION_CONFIRM_TTL_HOURS)
    with transaction.atomic():
        sub = (
            Subscription.objects.select_for_update()
            .filter(confirm_token=token, confirmed_at__isnull=True, created_at__gte=expires_after)
            .first()
        )
        if sub is None:
            return False

        pending = Subscription.objects.filter(email=sub.email, confirmed_at__isnull=True)
        replaced = Subscription.objects.filter(email=sub.email, confirmed_at__isnull=False)
        delivered = set(
            AlertDelivery.objects.filter(subscription__in=replaced).values_list(
                "proposition_id", flat=True
            )
        )
        AlertDelivery.objects.bulk_create(
            [AlertDelivery(subscription=sub, proposition_id=pk) for pk in delivered],
            ignore_conflicts=True,
        )
        replaced.delete()
        pending.update(is_active=True, confirmed_at=timezone.now())
    return True


def match_document(doc: dict, frequency: str | None = None) -> list[int]:
    if not doc:
        return []

    tokens = document_to_tsvector_tokens(doc)
    if not tokens:
        return []

    with connection.cursor() as cur:
        # array_to_tsvector, não to_tsvector: o parser de texto quebra
        # `casa_camara` em dois lexemas ('casa' e 'camara') e nada casaria com o
        # `query::tsquery`, que é cast cru e mantém o token inteiro.
        cur.execute(
            """
            SELECT id, ast, needs_revalidation
            FROM subscriptions
            WHERE is_active
              AND (%s::text IS NULL OR frequency = %s)
              AND array_to_tsvector(%s::text[]) @@ query::tsquery
            """,
            [frequency, frequency, sorted(set(tokens))],
        )
        rows = cur.fetchall()

    matches = []
    for sub_id, ast_data, needs_reval in rows:
        if needs_reval:
            ast_dict = ast_data if isinstance(ast_data, dict) else json.loads(ast_data)
            if reference_matches(ast_dict, doc):
                matches.append(sub_id)
        else:
            matches.append(sub_id)

    return sorted(matches)


def ast_matches_document(ast: dict, doc: dict) -> bool:
    """Avalia um AST avulso com a mesma semântica do match de inscrições.

    É usado pelo disparo manual do admin. Assim a pessoa pode experimentar um
    critério sem criar uma inscrição de teste que poderia receber alertas
    futuros.
    """
    if not doc:
        return False

    tokens = document_to_tsvector_tokens(doc)
    if not tokens:
        return False

    query, needs_revalidation = ast_to_tsquery(ast)
    with connection.cursor() as cur:
        cur.execute(
            "SELECT array_to_tsvector(%s::text[]) @@ %s::tsquery",
            [sorted(set(tokens)), query],
        )
        (matched,) = cur.fetchone()

    return bool(matched) and (not needs_revalidation or reference_matches(ast, doc))


def ast_matches_proposition(ast: dict, proposition_id: int) -> bool:
    """Atalho para testar um AST contra o documento de uma proposição."""
    return ast_matches_document(ast, build_document(proposition_id))


def match_proposition(proposition_id: int, frequency: str | None = None) -> list[int]:
    doc = build_document(proposition_id)
    return match_document(doc, frequency)
