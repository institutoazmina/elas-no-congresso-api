"""Deterministic legislative celerity derived from official event history."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.utils import timezone


@dataclass(frozen=True)
class Celerity:
    label: str
    days_without_movement: int
    movements_last_90_days: int
    last_event_at: datetime | None


def calculate_celerity(proposition, events: Iterable | None = None, *, today: date | None = None) -> Celerity:
    """Apply the public monitoring rule with inactivity taking precedence."""
    today = today or timezone.localdate()
    events = events if events is not None else proposition.events.filter(is_countable=True)
    event_dates = [event.event_at for event in events if event.is_countable and event.event_at]
    last_event_at = max(event_dates, default=None)
    reference_date = last_event_at.date() if last_event_at else proposition.presented_at
    days_without_movement = max(0, (today - reference_date).days)
    window_start = today - timedelta(days=90)
    movements_last_90_days = sum(1 for event_at in event_dates if event_at.date() >= window_start)

    if days_without_movement >= 360:
        label = "Esquecida"
    elif days_without_movement >= 180:
        label = "Travada"
    elif days_without_movement >= 90:
        label = "Lenta"
    elif movements_last_90_days >= 3:
        label = "Tá voando"
    else:
        label = "Rápida"

    return Celerity(label, days_without_movement, movements_last_90_days, last_event_at)
