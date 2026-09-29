from datetime import date, datetime, timedelta
from types import SimpleNamespace

from django.utils import timezone

from apps.propositions.celerity import calculate_celerity


def _event(day: date):
    return SimpleNamespace(
        event_at=timezone.make_aware(datetime.combine(day, datetime.min.time())),
        is_countable=True,
    )


def _proposition(presented_at: date):
    return SimpleNamespace(presented_at=presented_at)


def test_inactivity_thresholds_take_precedence_over_recent_count():
    today = date(2026, 9, 29)
    proposition = _proposition(today - timedelta(days=500))

    assert calculate_celerity(proposition, [_event(today - timedelta(days=90))], today=today).label == "Lenta"
    assert calculate_celerity(proposition, [_event(today - timedelta(days=180))], today=today).label == "Travada"
    assert calculate_celerity(proposition, [_event(today - timedelta(days=360))], today=today).label == "Esquecida"


def test_recent_movements_classify_rapid_and_flying():
    today = date(2026, 9, 29)
    proposition = _proposition(today - timedelta(days=120))

    rapid = calculate_celerity(proposition, [_event(today - timedelta(days=20))], today=today)
    flying = calculate_celerity(
        proposition,
        [_event(today - timedelta(days=20)), _event(today - timedelta(days=30)), _event(today - timedelta(days=40))],
        today=today,
    )

    assert (rapid.label, rapid.movements_last_90_days) == ("Rápida", 1)
    assert (flying.label, flying.movements_last_90_days) == ("Tá voando", 3)


def test_no_events_uses_presentation_date():
    today = date(2026, 9, 29)
    result = calculate_celerity(_proposition(today - timedelta(days=200)), [], today=today)

    assert (result.label, result.days_without_movement, result.movements_last_90_days) == (
        "Travada",
        200,
        0,
    )
