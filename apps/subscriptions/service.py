"""Subscription matching service (adapted from POC4 for Django)."""
from __future__ import annotations

import json

from django.db import connection

from .compiler import ast_to_tsquery, document_to_tsvector_string
from .document_builder import build_document
from .reference_matcher import matches as reference_matches


def register_subscription(email: str, ast: dict) -> int:
    from .models import Subscription

    tsq_str, needs_reval = ast_to_tsquery(ast)
    sub = Subscription.objects.create(
        email=email,
        ast=ast,
        query=tsq_str,
        needs_revalidation=needs_reval,
        is_active=False,
    )
    # Store compiled tsquery in DB as text; matching done via raw SQL cast
    return sub.pk


def match_document(doc: dict) -> list[int]:
    if not doc:
        return []

    vec = document_to_tsvector_string(doc)
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT id, ast, needs_revalidation
            FROM subscriptions
            WHERE is_active
              AND to_tsvector('simple', %s) @@ query::tsquery
            """,
            [vec],
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


def match_proposition(proposition_id: int) -> list[int]:
    doc = build_document(proposition_id)
    return match_document(doc)
