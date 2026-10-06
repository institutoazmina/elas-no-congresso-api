from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Event
from unittest.mock import Mock

import pytest
from django.db import close_old_connections

from apps.newsletters.models import WeeklyReport
from apps.newsletters.service import deliver_report, freeze_report, get_report


@pytest.mark.django_db(transaction=True)
def test_concurrent_workers_only_one_can_create():
    report = freeze_report(get_report(date(2026, 9, 28), date(2026, 10, 5)).pk, True)
    started, release = Event(), Event()
    client = Mock()
    client.find.return_value = None

    def create(*args):
        started.set()
        assert release.wait(timeout=10)
        return 123

    client.create.side_effect = create
    factory = Mock(return_value=client)

    def deliver():
        try:
            return deliver_report(report.pk, factory)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(deliver)
        try:
            assert started.wait(timeout=10)
            second = pool.submit(deliver).result(timeout=10)
            assert second.status == WeeklyReport.Status.DELIVERING
        finally:
            release.set()
        assert first.result(timeout=10).status == WeeklyReport.Status.DELIVERED
    client.create.assert_called_once()
    factory.assert_called_once()
