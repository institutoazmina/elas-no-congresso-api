"""One public identity per bill; official source records remain independent."""

from django.db.models import Q

from .celerity import calculate_celerity

# An explicitly recognized transfer stays private until its origin is available.
PUBLIC_ORIGIN_Q = Q(canonical_proposition__isnull=True) & ~Q(
    house="senado", originating_house="camara"
)


def public_sources(proposition):
    """Source records in order of presentation, original first."""
    transfers = list(proposition.transfers.all())
    return [proposition, *sorted(transfers, key=lambda source: (source.presented_at, source.pk))]


def public_events(proposition):
    sources = public_sources(proposition)
    return sorted(
        ((event, source) for source in sources for event in source.events.all()),
        key=lambda entry: (entry[0].event_at, entry[0].pk),
        reverse=True,
    )


def public_celerity(proposition, events):
    return calculate_celerity(proposition, (event for event, _ in events))
