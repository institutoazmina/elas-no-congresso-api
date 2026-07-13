"""Enfileira o backfill de anotações (JOB TEMPORÁRIO — remover após a carga).

Roda no container web (via `kamal app exec --reuse --roles web`) e apenas
ENFILEIRA o task Celery; o worker executa a carga async (~2-3h) e sobrevive.
"""

from django.core.management.base import BaseCommand

from apps.ingestion.tasks import backfill_annotations as backfill_task


class Command(BaseCommand):
    help = "Enfileira o task Celery de backfill retroativo de anotações."

    def add_arguments(self, parser):
        parser.add_argument("--start", type=int, default=0,
                            help="retoma a partir da linha N (não apaga)")
        parser.add_argument("--limit", type=int, default=None,
                            help="processa só as N primeiras linhas (teste)")
        parser.add_argument("--no-reset", action="store_true",
                            help="não apaga as anotações antes (retomada)")

    def handle(self, *args, **opts):
        reset = not opts["no_reset"]
        result = backfill_task.delay(
            reset=reset, start=opts["start"], limit=opts["limit"]
        )
        self.stdout.write(self.style.SUCCESS(
            f"Enfileirado backfill_annotations (task id={result.id}) — "
            f"reset={reset} start={opts['start']} limit={opts['limit']}. "
            f"Acompanhe: kamal app logs -r worker -f"
        ))
