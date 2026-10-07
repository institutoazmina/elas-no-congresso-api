"""No database/server required: check isolation, HTTP rendering, and cache safety."""

import json
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.test import AsyncClient, Client, SimpleTestCase, override_settings

from apps.propositions import explorer
from apps.propositions.performance import ExplorerTrace, current_trace, stage


class TraceTests(SimpleTestCase):
    def test_query_values_are_not_logged_and_groups_are_bounded(self):
        trace = ExplorerTrace(detailed_sql=True)
        for i in range(100):
            trace.execute(
                lambda *args: None, f"SELECT column_{i} WHERE name=%s", ["secret"], False, {}
            )
        report = trace.report()
        self.assertEqual(report["sql_count"], 100)
        self.assertLessEqual(len(report["sql_groups"]), 21)
        self.assertNotIn("secret", json.dumps(report))
        self.assertNotIn("SELECT", json.dumps(report))

    def test_stage_restores_context_on_failure(self):
        trace = ExplorerTrace()
        token = current_trace.set(trace)
        try:
            with self.assertRaises(ValueError), stage("failing"):
                raise ValueError()
            self.assertEqual(trace.phase, "request")
            self.assertIn("failing", trace.stages)
        finally:
            current_trace.reset(token)

    def test_bypass_never_touches_shared_cache(self):
        trace = ExplorerTrace(bypass_cache=True)
        token = current_trace.set(trace)
        try:
            with (
                patch.object(explorer, "cache") as cache,
                patch.object(explorer, "load_explorer_source", return_value=[]),
            ):
                self.assertEqual(explorer._all_activity(), [])
                cache.get.assert_not_called()
                cache.set.assert_not_called()
            self.assertEqual(trace.data["source_cache"], "bypass")
        finally:
            current_trace.reset(token)

    @override_settings(ACTIVITY_EXPLORER_TRACE_SAMPLE_RATE=1, ALLOWED_HOSTS=["testserver"])
    def test_real_pipeline_records_rendered_response_and_cache_hit(self):
        with (
            patch.object(explorer.cache, "get", return_value=[]),
            patch("apps.propositions.performance.logger.info") as log,
        ):
            response = Client().get("/api/v1/activity/explorer", {"search": "private query"})
        self.assertEqual(response.status_code, 200)
        report = json.loads(log.call_args.args[0])
        self.assertEqual(report["source_cache"], "hit")
        self.assertEqual(report["response_bytes"], len(response.content))
        self.assertEqual(report["request_id"], response["X-Explorer-Trace-ID"])
        self.assertNotIn("private query", json.dumps(report))
        self.assertIsNone(current_trace.get())

    @override_settings(ACTIVITY_EXPLORER_TRACE_SAMPLE_RATE=0)
    def test_command_forces_trace_even_when_sampling_disabled(self):
        output = StringIO()
        with patch.object(explorer.cache, "get", return_value=[]):
            call_command("profile_activity_explorer", runs=2, stdout=output)
        reports = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(reports), 2)
        self.assertTrue(all(r["status"] == 200 for r in reports))
        self.assertNotEqual(reports[0]["request_id"], reports[1]["request_id"])
        self.assertIsNone(current_trace.get())

    @override_settings(ACTIVITY_EXPLORER_TRACE_SAMPLE_RATE=1, ALLOWED_HOSTS=["testserver"])
    async def test_asgi_keeps_sql_wrapper_in_view_thread(self):
        def source():
            self.assertIsNotNone(current_trace.get())
            self.assertEqual(len(connection.execute_wrappers), 1)
            connection.execute_wrappers[0](lambda *args: None, "SELECT %s", [123], False, {})
            return []

        with (
            patch.object(explorer, "_all_activity", side_effect=source),
            patch("apps.propositions.performance.logger.info") as log,
        ):
            response = await AsyncClient().get("/api/v1/activity/explorer")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(log.call_args.args[0])["sql_count"], 1)
        self.assertIsNone(current_trace.get())

    @override_settings(ACTIVITY_EXPLORER_TRACE_SAMPLE_RATE=0, ALLOWED_HOSTS=["testserver"])
    def test_disabled_sampling_has_no_logs_wrapper_or_random_draw(self):
        def source():
            self.assertIsNone(current_trace.get())
            self.assertEqual(connection.execute_wrappers, [])
            return []

        with (
            patch.object(explorer, "_all_activity", side_effect=source),
            patch("apps.propositions.performance.logger.info") as log,
            patch("apps.propositions.performance.random.random") as random_draw,
        ):
            response = Client().get("/api/v1/activity/explorer")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("X-Explorer-Trace-ID", response)
        log.assert_not_called()
        random_draw.assert_not_called()

    def test_request_trace_keeps_sql_totals_without_hashing_queries(self):
        trace = ExplorerTrace()
        with patch("apps.propositions.performance.sha256") as digest:
            trace.execute(lambda *args: None, "SELECT %s", [1], False, {})
        self.assertEqual(trace.report()["sql_count"], 1)
        self.assertNotIn("sql_groups", trace.report())
        digest.assert_not_called()

    def test_command_outputs_report_without_duplicate_log(self):
        output = StringIO()
        with (
            patch.object(explorer.cache, "get", return_value=[]),
            patch("apps.propositions.performance.logger.info") as log,
        ):
            call_command("profile_activity_explorer", stdout=output)
        self.assertIn("sql_groups", json.loads(output.getvalue()))
        log.assert_not_called()
