"""Fill missing parliamentarian photos from the bundled historical crosswalk."""

import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from apps.legislatures.models import Parliamentarian
from apps.propositions.activity import invalidate_activity_cache
from apps.propositions.models import Proposition


class Command(BaseCommand):
    help = "Fill missing parliamentarian photos from data/parlamentares.csv."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv-path",
            default=Path(settings.BASE_DIR) / "data" / "parlamentares.csv",
            help="Path to the historical parliamentarian crosswalk.",
        )

    def handle(self, *args, **options):
        csv_path = Path(options["csv_path"])
        if not csv_path.is_file():
            raise CommandError(f"Legacy parliamentarian crosswalk not found: {csv_path}")

        updated = skipped = 0
        updated_ids = []
        with csv_path.open(encoding="utf-8", newline="") as source:
            for row in csv.DictReader(source):
                name = (row.get("nome") or "").strip()
                photo_url = (row.get("foto") or "").strip()
                if not name or not photo_url:
                    continue

                matches = list(
                    Parliamentarian.objects.filter(full_name__iexact=name).filter(
                        Q(photo_url__isnull=True) | Q(photo_url="")
                    )
                )
                if len(matches) != 1:
                    skipped += 1
                    continue

                parliamentarian = matches[0]
                parliamentarian.photo_url = photo_url
                parliamentarian.save(update_fields=["photo_url", "updated_at"])
                updated_ids.append(parliamentarian.pk)
                updated += 1

        if updated:
            propositions = Proposition.objects.filter(
                authors__parliamentarian_id__in=updated_ids
            ).distinct()
            invalidate_activity_cache(propositions)
        self.stdout.write(self.style.SUCCESS(f"Updated {updated} photos; skipped {skipped} ambiguous or known records."))
