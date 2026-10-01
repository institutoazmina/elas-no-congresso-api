"""Import public religious-identity classifications for Câmara members."""

import csv
from io import StringIO
from pathlib import Path
from urllib.request import urlopen

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.legislatures.religion_mapper import ReligionMappingError, map_religion_rows

RELIGION_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1PHKg_hQ5imp81SYcyVevSCdH3PNj1u30SMpEiYOk1y8/export?format=csv"
)


class Command(BaseCommand):
    help = "Importa identidades religiosas da planilha pública para parlamentares da Câmara."

    def add_arguments(self, parser):
        source = parser.add_mutually_exclusive_group()
        source.add_argument("--csv-path", type=Path, help="Arquivo CSV baixado da planilha pública.")
        source.add_argument("--url", default=RELIGION_CSV_URL, help="URL CSV da planilha pública.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra o resultado do mapeamento sem atualizar o banco.",
        )

    def _source_text(self, options) -> str:
        csv_path = options.get("csv_path")
        if csv_path:
            if not csv_path.is_file():
                raise CommandError(f"Arquivo CSV não encontrado: {csv_path}")
            return csv_path.read_text(encoding="utf-8-sig")
        try:
            with urlopen(options["url"], timeout=30) as response:  # noqa: S310 - URL explícita do comando
                return response.read().decode("utf-8-sig")
        except OSError as error:
            raise CommandError(f"Não foi possível baixar a planilha: {error}") from error

    def handle(self, *args, **options):
        try:
            result = map_religion_rows(csv.DictReader(StringIO(self._source_text(options))))
        except ReligionMappingError as error:
            raise CommandError(str(error)) from error

        if not result.values:
            raise CommandError("A planilha não contém linhas válidas com ID_Camara e Identidade Religiosa.")

        dry_run = options["dry_run"]
        counts = {
            "updated": 0,
            "unchanged": 0,
            "unmatched": 0,
            "ambiguous": 0,
            "source_conflicts": len(result.conflicting_ids),
        }
        with transaction.atomic(), connection.cursor() as cursor:
            for external_id, religion in result.values.items():
                cursor.execute(
                    """
                    SELECT p.id, p.religion
                    FROM parliamentarian_terms AS term
                    JOIN parliamentarians AS p ON p.id = term.parliamentarian_id
                    WHERE term.house = %s AND term.external_id = %s
                    GROUP BY p.id, p.religion
                    """,
                    ["camara", external_id],
                )
                matches = cursor.fetchall()
                if not matches:
                    counts["unmatched"] += 1
                    continue
                if len(matches) > 1:
                    counts["ambiguous"] += 1
                    continue

                parliamentarian_id, current_religion = matches[0]
                if current_religion == religion:
                    counts["unchanged"] += 1
                    continue
                if not dry_run:
                    cursor.execute(
                        """
                        UPDATE parliamentarians
                        SET religion = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        [religion, parliamentarian_id],
                    )
                counts["updated"] += 1

        action = "Atualizaria" if dry_run else "Atualizou"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {counts['updated']}; sem mudança {counts['unchanged']}; "
                f"sem mandato correspondente {counts['unmatched']}; ambíguos {counts['ambiguous']}; "
                f"conflitos na fonte {counts['source_conflicts']}."
            )
        )
