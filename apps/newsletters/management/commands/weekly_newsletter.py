from datetime import date, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.newsletters.collection import refresh_batch
from apps.newsletters.models import WeeklyReport
from apps.newsletters.report import REPORT_TZ, build_snapshot, render, reporting_week
from apps.newsletters.service import deliver_report, freeze_report, get_report
from apps.newsletters.substack import DraftOnlyClient
from apps.propositions.models import Proposition


class Command(BaseCommand):
    help = "Prepara/exporta um Radar semanal ou cria somente um rascunho no Substack."

    def add_arguments(self, parser):
        parser.add_argument(
            "--week-start", type=date.fromisoformat, help="Segunda-feira YYYY-MM-DD"
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Somente leitura: imprime o relatório, sem coletar ou criar rascunho.",
        )
        parser.add_argument("--format", choices=["markdown", "html"], default="markdown")
        parser.add_argument(
            "--refresh", action="store_true", help="Atualiza históricos oficiais antes de preparar."
        )
        parser.add_argument(
            "--deliver", action="store_true", help="Cria somente rascunho; nunca publica."
        )
        parser.add_argument(
            "--report-id", type=int, help="Repetir/reconciliar entrega de relatório preparado."
        )
        parser.add_argument(
            "--attach-draft-id",
            type=int,
            help="Reconciliação manual: vincula um rascunho existente, verificando seu estado.",
        )

    def handle(self, *args, **options):
        if options["dry_run"] and (
            options["refresh"]
            or options["deliver"]
            or options["report_id"]
            or options["attach_draft_id"]
        ):
            raise CommandError("--dry-run não pode coletar, entregar ou reconciliar.")
        if options["report_id"]:
            if options["week_start"] or options["refresh"]:
                raise CommandError("--report-id não pode regenerar o relatório.")
            try:
                report = WeeklyReport.objects.get(pk=options["report_id"])
            except WeeklyReport.DoesNotExist as exc:
                raise CommandError("Relatório não encontrado.") from exc
            if options["attach_draft_id"]:
                if report.status != WeeklyReport.Status.UNCERTAIN:
                    raise CommandError("Vinculação manual exige entrega incerta.")
                client = DraftOnlyClient(report.publication_url)
                try:
                    client.verify(options["attach_draft_id"])
                finally:
                    client.close()
                report.draft_id = options["attach_draft_id"]
                report.save(update_fields=["draft_id", "updated_at"])
        else:
            if options["attach_draft_id"]:
                raise CommandError("--attach-draft-id exige --report-id.")
            start = (
                options["week_start"]
                or reporting_week(timezone.now().astimezone(REPORT_TZ).date())[0]
            )
            if start.weekday() != 0:
                raise CommandError("--week-start deve ser uma segunda-feira.")
            end = start + timedelta(days=7)
            if end > timezone.now().astimezone(REPORT_TZ).date():
                raise CommandError("A semana deve estar encerrada.")
            if options["dry_run"]:
                markdown, html = render(build_snapshot(start, end))
                self.stdout.write(html if options["format"] == "html" else markdown)
                return
            report = get_report(start, end)
            if report.status == WeeklyReport.Status.COLLECTING:
                results = {}
                ids = list(Proposition.objects.order_by("pk").values_list("pk", flat=True))
                if options["refresh"]:
                    for offset in range(0, len(ids), settings.WEEKLY_NEWSLETTER_BATCH_SIZE):
                        results.update(
                            refresh_batch(
                                ids[offset : offset + settings.WEEKLY_NEWSLETTER_BATCH_SIZE]
                            )
                        )
                report.collection = {"targets": ids, "results": results, "manual": True}
                report.save(update_fields=["collection", "updated_at"])
                complete = bool(options["refresh"]) and all(
                    results.get(str(pk)) == "ok" for pk in ids
                )
                report = freeze_report(report.pk, complete)
        if options["deliver"]:
            report = deliver_report(report.pk)
            if report.status != WeeklyReport.Status.DELIVERED:
                raise CommandError(
                    f"Relatório {report.pk}: {report.get_status_display()}. Exportação preservada no admin."
                )
        self.stdout.write(
            f"Relatório {report.pk}: {report.get_status_display()} {report.draft_url}"
        )
