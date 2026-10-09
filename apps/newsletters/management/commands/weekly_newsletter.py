from datetime import date, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.newsletters.collection import refresh_batch
from apps.newsletters.freshness import coverage_complete, source_coverage
from apps.newsletters.models import WeeklyReport
from apps.newsletters.report import REPORT_TZ, build_snapshot, render, reporting_week
from apps.newsletters.service import deliver_report, freeze_report, get_report
from apps.newsletters.substack import AuthenticationRequiredError, DraftOnlyClient
from apps.propositions.models import Proposition


class Command(BaseCommand):
    help = "Prepara/exporta um Radar semanal ou cria somente um rascunho no Substack."

    def add_arguments(self, parser):
        parser.add_argument(
            "--week-start", type=date.fromisoformat, help="Segunda-feira YYYY-MM-DD"
        )
        parser.add_argument(
            "--check-auth",
            action="store_true",
            help="Verifica sessão e acesso a rascunhos, sem escrita.",
        )
        parser.add_argument(
            "--allow-incomplete",
            action="store_true",
            help="Permite entrega manual com aviso de cobertura incompleta.",
        )
        parser.add_argument(
            "--start-date",
            type=date.fromisoformat,
            help="Início inclusivo YYYY-MM-DD (uso manual).",
        )
        parser.add_argument(
            "--end-date", type=date.fromisoformat, help="Fim inclusivo YYYY-MM-DD, até hoje."
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
        if options["check_auth"]:
            client = None
            try:
                client = DraftOnlyClient(settings.SUBSTACK_PUBLICATION_URL)
                client.check_access()
            except AuthenticationRequiredError as exc:
                raise CommandError(
                    "Substack: renovar sessão e verificar acesso à publicação."
                ) from exc
            except Exception as exc:
                raise CommandError(
                    f"Substack: verificação indisponível ({type(exc).__name__})."
                ) from exc
            finally:
                if client:
                    client.close()
            self.stdout.write(
                "Substack: acesso aos rascunhos verificado; nenhuma escrita executada."
            )
            return
        custom_period = options["start_date"] is not None or options["end_date"] is not None
        if custom_period and (options["week_start"] or options["report_id"]):
            raise CommandError(
                "Datas manuais não podem ser usadas com --week-start ou --report-id."
            )
        if custom_period and (options["start_date"] is None or options["end_date"] is None):
            raise CommandError("Informar --start-date e --end-date juntos.")
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
            today = timezone.now().astimezone(REPORT_TZ).date()
            if custom_period:
                start = options["start_date"]
                last_day = options["end_date"]
                if start > last_day:
                    raise CommandError("A data inicial deve ser anterior ou igual à final.")
                if last_day > today:
                    raise CommandError("A data final não pode estar no futuro.")
                end = last_day + timedelta(days=1)
            else:
                start = options["week_start"] or reporting_week(today)[0]
                if start.weekday() != 0:
                    raise CommandError("--week-start deve ser uma segunda-feira.")
                end = start + timedelta(days=7)
                if end > today:
                    raise CommandError("A semana deve estar encerrada.")
            if options["dry_run"]:
                # Somente leitura: a cobertura entra no aviso, sem gravar relatório.
                coverage = source_coverage(start, end)
                complete = coverage_complete(coverage)
                if not complete:
                    self.stderr.write(f"Cobertura incompleta: {coverage['discovery']}")
                markdown, html = render(build_snapshot(start, end), complete)
                self.stdout.write(html if options["format"] == "html" else markdown)
                return
            try:
                report = get_report(start, end)
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
            if options["refresh"] and report.status != WeeklyReport.Status.COLLECTING:
                # Repetir o comando é idempotente; só avisa que nada foi recoletado.
                self.stderr.write(
                    f"Relatório {report.pk} já congelado; --refresh não altera o conteúdo."
                )
            if report.status == WeeklyReport.Status.COLLECTING:
                results = {}
                ids = (
                    list(Proposition.objects.order_by("pk").values_list("pk", flat=True))
                    if options["refresh"]
                    else []
                )
                if options["refresh"]:
                    for offset in range(0, len(ids), settings.WEEKLY_NEWSLETTER_BATCH_SIZE):
                        results.update(
                            refresh_batch(
                                ids[offset : offset + settings.WEEKLY_NEWSLETTER_BATCH_SIZE]
                            )
                        )
                        processed = min(offset + settings.WEEKLY_NEWSLETTER_BATCH_SIZE, len(ids))
                        if processed % 50 == 0 or processed == len(ids):
                            self.stdout.write(f"Históricos atualizados: {processed}/{len(ids)}")
                            self.stdout.flush()
                report.collection = {"targets": ids, "results": results, "manual": True}
                report.save(update_fields=["collection", "updated_at"])
                if options["refresh"]:
                    complete = all(results.get(str(pk)) == "ok" for pk in ids)
                else:
                    report.collection = source_coverage(start, end)
                    report.collection["manual"] = True
                    report.save(update_fields=["collection", "updated_at"])
                    complete = coverage_complete(report.collection)
                report = freeze_report(report.pk, complete)
        if options["deliver"]:
            if (
                not report.is_complete
                and not options["allow_incomplete"]
                and report.status != WeeklyReport.Status.DELIVERED
            ):
                raise CommandError(
                    f"Relatório {report.pk}: cobertura diária incompleta. Exportação preservada; --allow-incomplete exige revisão humana. {report.collection.get('discovery', {})}"
                )
            report = deliver_report(report.pk)
            if report.status != WeeklyReport.Status.DELIVERED:
                raise CommandError(
                    f"Relatório {report.pk}: {report.get_status_display()}. Exportação preservada no admin."
                )
        self.stdout.write(
            f"Relatório {report.pk}: {report.get_status_display()} {report.draft_url}\n"
            f"Cobertura das fontes: {report.collection.get('discovery', {})}\n"
            f"{len(report.snapshot)} proposições; coleta "
            f"{'completa' if report.is_complete else 'incompleta'}."
        )
