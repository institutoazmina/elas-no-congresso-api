"""Ajustes de conexão exclusivos do processo web."""

from django.conf import settings
from django.db.backends.signals import connection_created


def apply_statement_timeout(sender, connection, **kwargs):
    """Uma query patológica (busca sem índice, filtro combinado caro) não pode
    prender a API: o Postgres a cancela e a requisição falha sozinha."""
    if settings.DB_STATEMENT_TIMEOUT_MS and connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, false)",
                [f"{settings.DB_STATEMENT_TIMEOUT_MS}ms"],
            )


def install_statement_timeout():
    connection_created.connect(apply_statement_timeout, dispatch_uid="web-statement-timeout")
