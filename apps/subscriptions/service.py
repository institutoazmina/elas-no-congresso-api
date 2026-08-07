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
    # recebe, não somando uma segunda inscrição no mesmo endereço.
    Subscription.objects.filter(email=email).delete()

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


def match_proposition(proposition_id: int, frequency: str | None = None) -> list[int]:
    doc = build_document(proposition_id)
    return match_document(doc, frequency)
