"""Exercise the real Django request pipeline in the production environment."""

import cProfile
import json
from urllib.parse import parse_qs

from django.core.management.base import BaseCommand, CommandError
from django.test import Client, override_settings

from apps.propositions.performance import ExplorerTrace, current_trace


class Command(BaseCommand):
    help = "Measure explorer stages/SQL without clearing the live cache. Emits JSON per request."

    def add_arguments(self, parser):
        parser.add_argument(
            "--query", default="", help="URL query string (repeat list filters normally)"
        )
        parser.add_argument("--runs", type=int, default=1)
        parser.add_argument(
            "--bypass-cache",
            action="store_true",
            help="Rebuild source without reading or writing its shared cache",
        )
        parser.add_argument("--profile", help="Optional cProfile output file (adds overhead)")

    def handle(self, *args, **options):
        if not 1 <= options["runs"] <= 20:
            raise CommandError("--runs must be between 1 and 20")
        if options["profile"] and options["runs"] != 1:
            raise CommandError("Use --runs 1 with --profile")
        query = parse_qs(options["query"], keep_blank_values=True)
        profiler = cProfile.Profile() if options["profile"] else None
        # Overrides affect only this process, never the running web service.
        with override_settings(ALLOWED_HOSTS=["testserver"], SECURE_SSL_REDIRECT=False):
            client = Client(raise_request_exception=False)
            for run in range(options["runs"]):
                trace = ExplorerTrace(
                    bypass_cache=options["bypass_cache"], detailed_sql=True, emit_log=False
                )
                trace.data.update(origin="management_command", run=run + 1)
                token = current_trace.set(trace)
                try:
                    if profiler:
                        profiler.enable()
                    response = client.get("/api/v1/activity/explorer", data=query)
                finally:
                    if profiler:
                        profiler.disable()
                        profiler.dump_stats(options["profile"])
                    current_trace.reset(token)
                self.stdout.write(json.dumps(trace.report(), ensure_ascii=False))
                if response.status_code != 200:
                    raise CommandError(
                        f"Explorer returned HTTP {response.status_code}; see application logs"
                    )
