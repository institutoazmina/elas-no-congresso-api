from django.core.management.base import BaseCommand
from django_celery_beat.models import PeriodicTask

from apps.ingestion.models import IngestionCheckpoint, IngestionRun
from apps.ingestion.tasks import (
    ingest_camara,
    ingest_senado,
    reconcile_daily_propositions,
    recover_pending_content,
    sync_daily_batch,
)


class Command(BaseCommand):
    help = "Enfileira coleta incremental/baseline ou consulta progresso persistido."

    def add_arguments(self, parser):
        parser.add_argument(
            "--mode", choices=["daily", "bootstrap", "catchup", "retry", "status"], default="status"
        )

    def handle(self, *args, **options):
        mode = options["mode"]
        if mode == "catchup":
            # Retain run/item audit; explicitly abandon continuous coverage across the gap.
            IngestionCheckpoint.objects.update(
                covered_since=None, covered_until=None, active_run=None, baseline_complete=False
            )
            from apps.propositions.models import Proposition

            Proposition.objects.update(reconciled_at=None)
        if mode != "status":
            PeriodicTask.objects.filter(
                task="apps.ingestion.tasks.refresh_enacted_proposition_statuses"
            ).update(enabled=False)
            if mode == "retry":
                ingest_camara.delay()
                ingest_senado.delay()
                for run in IngestionRun.objects.filter(
                    status__in=["failed", "running"], discovery_complete=True
                ):
                    run.items.filter(status="failed").update(status="pending", attempts=0)
                    run.status = run.Status.RUNNING
                    run.save(update_fields=["status"])
                    sync_daily_batch.delay(run.pk)
                recover_pending_content.delay()
            else:
                ingest_camara.delay()
                ingest_senado.delay()
                if mode in {"bootstrap", "catchup"}:
                    reconcile_daily_propositions.delay(full_baseline=True)
            self.stdout.write(
                f"Modo {mode}: trabalho enfileirado; consultar --mode status para acompanhar."
            )
        for checkpoint in IngestionCheckpoint.objects.order_by("house"):
            self.stdout.write(
                f"{checkpoint.house}: baseline={checkpoint.baseline_complete}; cobertura={checkpoint.covered_since} até {checkpoint.covered_until}"
            )
        for run in IngestionRun.objects.order_by("-started_at")[:6]:
            counts = {
                status: run.items.filter(status=status).count()
                for status in ["pending", "succeeded", "skipped", "failed"]
            }
            self.stdout.write(f"Run {run.pk} {run.house}/{run.kind}: {run.status}; {counts}")
