import json

from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.classification_backfill import backfill_status, prepare_missing_evaluations


class Command(BaseCommand):
    help = "Consulta ou enfileira QuitérIA para proposições sem avaliação humana ou IA completa."

    def add_arguments(self, parser):
        parser.add_argument(
            "--mode", choices=["preview", "status", "queue", "retry"], default="preview"
        )
        parser.add_argument("--limit", type=int, default=0, help="Zero inclui todos os candidatos.")

    def handle(self, *args, **options):
        if options["limit"] < 0:
            raise CommandError("O limite deve ser zero (todos) ou positivo.")
        if options["mode"] in {"queue", "retry"}:
            try:
                result = prepare_missing_evaluations(
                    limit=options["limit"], retry_failed=options["mode"] == "retry"
                )
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write("Backfill: " + json.dumps(result, sort_keys=True))
        self.stdout.write("Evaluation coverage: " + json.dumps(backfill_status(), sort_keys=True))
