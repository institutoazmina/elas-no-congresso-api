"""Bounded, opt-in explorer traces. Never record SQL parameters or filter values."""

import json
import logging
import os
import random
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
from time import perf_counter, thread_time
from uuid import uuid4

from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)
current_trace = ContextVar("explorer_trace", default=None)


class ExplorerTrace:
    def __init__(self, *, bypass_cache=False, detailed_sql=False, emit_log=True):
        self.bypass_cache = bypass_cache
        self.detailed_sql = detailed_sql
        self.emit_log = emit_log
        self.stages = defaultdict(float)
        self.sql = {}
        self.sql_count = 0
        self.sql_ms = 0.0
        self.data = {
            "event": "activity_explorer_performance",
            "request_id": uuid4().hex,
            "pid": os.getpid(),
        }
        self.phase = "request"

    def execute(self, execute, sql, params, many, context):
        start = perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            elapsed = (perf_counter() - start) * 1000
            self.sql_count += 1
            self.sql_ms += elapsed
            if self.detailed_sql:
                # Hash the template only; values and raw SQL never enter logs.
                key = (self.phase, sha256(sql.encode()).hexdigest()[:16])
                if key not in self.sql and len(self.sql) >= 20:
                    key = ("other", "overflow")
                row = self.sql.setdefault(
                    key, {"stage": key[0], "fingerprint": key[1], "count": 0, "ms": 0.0}
                )
                row["count"] += 1
                row["ms"] += elapsed

    def report(self):
        report = {
            **self.data,
            "stages_ms": {k: round(v, 3) for k, v in self.stages.items()},
            "sql_count": self.sql_count,
            "sql_execute_ms": round(self.sql_ms, 3),
        }
        if self.detailed_sql:
            report["sql_groups"] = [
                {**row, "ms": round(row["ms"], 3)}
                for row in sorted(self.sql.values(), key=lambda r: -r["ms"])
            ]
        return report


@contextmanager
def stage(name):
    trace = current_trace.get()
    if trace is None:
        yield
        return
    previous = trace.phase
    trace.phase = name
    start = perf_counter()
    try:
        yield
    finally:
        trace.stages[name] += (perf_counter() - start) * 1000
        trace.phase = previous


def annotate(**values):
    trace = current_trace.get()
    if trace is not None:
        trace.data.update(values)


class ExplorerPerformanceMiddleware:
    """Sync middleware keeps the SQL wrapper in the sync view's database thread."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.rstrip("/") != "/api/v1/activity/explorer":
            return self.get_response(request)
        trace = current_trace.get()
        if trace is None:
            rate = settings.ACTIVITY_EXPLORER_TRACE_SAMPLE_RATE
            if rate <= 0 or random.random() >= rate:
                return self.get_response(request)
            trace = ExplorerTrace()
        token = current_trace.set(trace)
        start, cpu = perf_counter(), thread_time()
        try:
            with connection.execute_wrapper(trace.execute):
                response = self.get_response(request)
            trace.data.update(
                status=response.status_code,
                response_bytes=len(response.content) if not response.streaming else None,
            )
            response["X-Explorer-Trace-ID"] = trace.data["request_id"]
            return response
        finally:
            trace.data.update(
                total_ms=round((perf_counter() - start) * 1000, 3),
                thread_cpu_ms=round((thread_time() - cpu) * 1000, 3),
            )
            current_trace.reset(token)
            if trace.emit_log:
                logger.info(json.dumps(trace.report(), ensure_ascii=False))
