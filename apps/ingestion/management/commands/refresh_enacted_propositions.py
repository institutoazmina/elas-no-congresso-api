from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.tasks import refresh_enacted_propositions
from apps.propositions.models import Proposition


class Command(BaseCommand):
    help = "Atualiza status e leis resultantes das proposições avaliadas."

    def add_arguments(self, parser):
        parser.add_argument("--house", choices=["camara", "senado"])
        parser.add_argument("--limit", type=int)
        parser.add_argument("--strict", action="store_true")

    def handle(self, *args, **options):
        queryset = Proposition.objects.filter(annotations__is_favorable__isnull=False).distinct()
        if options["house"]:
            queryset = queryset.filter(house=options["house"])
        if options["limit"] is not None:
            queryset = queryset.order_by("pk")[: options["limit"]]

        stats = refresh_enacted_propositions(queryset)
        if stats["failed"] and options["strict"]:
            raise CommandError(str(stats))
        if stats["failed"]:
            self.stderr.write(self.style.WARNING(str(stats)))
        self.stdout.write(self.style.SUCCESS(str(stats)))
