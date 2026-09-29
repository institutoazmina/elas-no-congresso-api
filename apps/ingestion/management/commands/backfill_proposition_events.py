from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.ingestion.clients.camara import CamaraClient
from apps.ingestion.clients.senado import SenadoClient
from apps.ingestion.mappers import (
    map_camara_events,
    map_senado_event,
    map_senado_process_events,
    map_senado_process_status,
)
from apps.ingestion.tasks import _persist_events
from apps.propositions.models import Proposition


class Command(BaseCommand):
    help = "Reconstroi o histórico oficial de movimentações das proposições monitoradas."

    def add_arguments(self, parser):
        parser.add_argument("--house", choices=["camara", "senado"])
        parser.add_argument("--offset", type=int, default=0)
        parser.add_argument("--limit", type=int)

    def handle(self, *args, **options):
        queryset = Proposition.objects.order_by("pk")
        if options["house"]:
            queryset = queryset.filter(house=options["house"])
        propositions = list(queryset[options["offset"] :])
        if options["limit"] is not None:
            propositions = propositions[: options["limit"]]

        stats = {"processed": 0, "events": 0, "failed": 0}
        with CamaraClient() as camara, SenadoClient() as senado:
            for proposition in propositions:
                try:
                    if proposition.house == "camara":
                        events = map_camara_events(camara.fetch_tramitations(proposition.external_id))
                    else:
                        process_id = (proposition.raw_payload or {}).get("_senado_process_id")
                        if process_id:
                            process = senado.fetch_process(int(process_id))
                            events = map_senado_process_events(process)
                            status = map_senado_process_status(process)
                            Proposition.objects.filter(pk=proposition.pk).update(**status)
                        else:
                            event = map_senado_event(senado.fetch_movements(proposition.external_id))
                            events = [event] if event else []
                    with transaction.atomic():
                        _persist_events(proposition, events)
                    stats["processed"] += 1
                    stats["events"] += len(events)
                except Exception as error:
                    stats["failed"] += 1
                    self.stderr.write(f"{proposition.pk} ({proposition}): {error}")

        if stats["failed"]:
            raise CommandError(str(stats))
        self.stdout.write(self.style.SUCCESS(str(stats)))
