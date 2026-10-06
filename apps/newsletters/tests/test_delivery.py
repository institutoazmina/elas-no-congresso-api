from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.newsletters.models import WeeklyReport
from apps.newsletters.service import deliver_report, freeze_report, get_report
from apps.newsletters.substack import AuthenticationRequiredError, DraftOnlyClient


@pytest.fixture
def report(db):
    report = get_report(date(2026, 9, 28), date(2026, 10, 5))
    return freeze_report(report.pk, True)


def client():
    mock = Mock()
    mock.find.return_value = None
    mock.create.return_value = 123
    return mock


def test_adapter_explicit_flags_and_verification():
    api = Mock()
    api.create_draft_from_markdown.return_value = {"draft": {"id": 123}}
    api.get_draft.return_value = {"id": 123, "draft_body": "{}", "post_date": None}
    adapter = DraftOnlyClient("https://example.substack.com", api)
    assert adapter.create("title", "body") == 123
    assert adapter.verify(123)["id"] == 123
    kwargs = api.create_draft_from_markdown.call_args.kwargs
    assert all(
        kwargs[key] is False for key in ["publish", "prepublish", "send", "share_automatically"]
    )
    api.publish_draft.assert_not_called()
    api.schedule_draft.assert_not_called()
    api.get_draft.return_value["post_date"] = "2026-10-10"
    with pytest.raises(ValueError):
        adapter.verify(123)


def test_http_guard_blocks_all_other_writes():
    api = SimpleNamespace(publication_url="https://example.substack.com/api/v1", _session=Mock())
    adapter = DraftOnlyClient("https://example.substack.com", api)
    original = api._session.request
    adapter._restrict_requests()
    api._session.request("POST", "https://example.substack.com/api/v1/drafts", json={})
    for path in ["drafts/1/publish", "drafts/1/scheduled_release", "image"]:
        with pytest.raises(ValueError):
            api._session.request("POST", f"https://example.substack.com/api/v1/{path}")
    with pytest.raises(ValueError):
        api._session.request("PUT", "https://example.substack.com/api/v1/drafts/1")
    assert original.call_count == 1


def test_pinned_sdk_conversion_creates_only_one_draft_request(monkeypatch, settings):
    import requests

    settings.SUBSTACK_COOKIES_STRING = "substack.sid=test-session"
    calls = []
    draft = {"id": 123, "draft_body": "{}", "post_date": None}

    def request(session, method, url, **kwargs):
        calls.append((method.upper(), url, kwargs))
        assert session.headers["User-Agent"].startswith("Mozilla/5.0")
        if url.endswith("/user/profile/self"):
            data = {
                "id": 42,
                "publicationUsers": [{"publication": {"subdomain": "example", "id": 1}}],
            }
        elif method.upper() == "POST":
            assert url == "https://example.substack.com/api/v1/drafts"
            assert "LEGENDA" in kwargs["json"]["draft_body"]
            data = draft
        elif url.endswith("/drafts"):
            # The live endpoint rejects pages of 100 with HTTP 400.
            if kwargs["params"]["limit"] > 25:
                return SimpleNamespace(status_code=400, text='{"error":"Invalid value"}')
            data = []
        elif url.endswith("/drafts/123"):
            data = draft
        else:
            assert url.startswith("https://substack.com/sign-in?")
            data = {}
        return SimpleNamespace(status_code=200, json=lambda: data)

    monkeypatch.setattr(requests.Session, "request", request)
    adapter = DraftOnlyClient("https://example.substack.com")
    try:
        assert adapter.find("Weekly Radar") is None
        assert (
            adapter.create(
                "Weekly Radar",
                "**LEGENDA**\n\n## Radar da Câmara\n\n🆕 **Ementa** — [PL 1/2026](https://www.camara.leg.br/propostas-legislativas/1)",
            )
            == 123
        )
        adapter.verify(123)
    finally:
        adapter.close()
    assert [url for method, url, _ in calls if method != "GET"] == [
        "https://example.substack.com/api/v1/drafts"
    ]


@pytest.mark.parametrize("duplicate", [False, True])
def test_find_checks_later_pages_for_matches_and_duplicates(duplicate):
    drafts = [{"id": index, "draft_title": f"Other {index}"} for index in range(25)]
    if duplicate:
        drafts[0]["draft_title"] = "Weekly Radar"
    drafts.append({"id": 123, "draft_title": "Weekly Radar"})

    def page(*, offset, limit):
        if limit > 25:
            raise ValueError("Substack rejects oversized draft pages")
        return drafts[offset : offset + limit]

    adapter = DraftOnlyClient("https://example.substack.com", SimpleNamespace(get_drafts=page))
    if duplicate:
        with pytest.raises(ValueError, match="Mais de um rascunho"):
            adapter.find("Weekly Radar")
    else:
        assert adapter.find("Weekly Radar") == 123


@pytest.mark.django_db
def test_delivery_is_idempotent_and_preserves_human_edits(report):
    mock = client()
    factory = Mock(return_value=mock)
    result = deliver_report(report.pk, factory)
    assert result.status == WeeklyReport.Status.DELIVERED
    assert result.draft_url.endswith("/publish/post/123")
    deliver_report(report.pk, factory)
    assert mock.create.call_count == 1
    assert factory.call_count == 1
    mock.close.assert_called_once()


@pytest.mark.django_db
def test_upload_timeout_reconciles_without_duplicate(report):
    mock = client()
    mock.create.side_effect = TimeoutError("secret cookie must not be stored")
    result = deliver_report(report.pk, lambda _: mock)
    assert result.status == WeeklyReport.Status.UNCERTAIN
    assert "secret cookie" not in result.error
    deliver_report(report.pk, lambda _: mock)
    assert mock.create.call_count == 1
    mock.find.return_value = 123
    result = deliver_report(report.pk, lambda _: mock)
    assert result.status == WeeklyReport.Status.DELIVERED
    assert mock.create.call_count == 1


@pytest.mark.django_db
def test_readback_failure_saves_id_before_retry(report):
    mock = client()
    mock.verify.side_effect = TimeoutError
    result = deliver_report(report.pk, lambda _: mock)
    assert result.draft_id == 123
    mock.verify.side_effect = None
    deliver_report(report.pk, lambda _: mock)
    assert mock.create.call_count == 1


@pytest.mark.django_db
def test_expired_session_and_killed_worker(report):
    factory = Mock(side_effect=AuthenticationRequiredError)
    result = deliver_report(report.pk, factory)
    assert result.status == WeeklyReport.Status.AUTH_REQUIRED
    report.refresh_from_db()
    report.status = WeeklyReport.Status.DELIVERING
    report.attempt_started_at = timezone.now() - timedelta(minutes=15)
    report.save()
    mock = client()
    result = deliver_report(report.pk, lambda _: mock)
    assert result.status == WeeklyReport.Status.UNCERTAIN
    mock.create.assert_not_called()


@pytest.mark.django_db
def test_active_reservation_and_existing_remote_draft(report):
    report.status = WeeklyReport.Status.DELIVERING
    report.attempt_started_at = timezone.now()
    report.save()
    factory = Mock()
    deliver_report(report.pk, factory)
    factory.assert_not_called()
    report.status = WeeklyReport.Status.READY
    report.save()
    mock = client()
    mock.find.return_value = 456
    result = deliver_report(report.pk, lambda _: mock)
    assert result.draft_id == 456
    mock.create.assert_not_called()


@pytest.mark.django_db
def test_on_time_delivery_clock(report, monkeypatch):
    from apps.newsletters.report import REPORT_TZ

    monkeypatch.setattr(timezone, "now", lambda: datetime(2026, 10, 5, 6, 46, tzinfo=REPORT_TZ))
    result = deliver_report(report.pk, lambda _: client())
    assert result.deadline_missed is False
