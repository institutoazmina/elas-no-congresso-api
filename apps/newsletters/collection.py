"""Refresh existing records without changing approval or generating newsletter prose."""

from django.db import transaction

from apps.ingestion.clients.camara import CamaraClient
from apps.ingestion.clients.senado import SenadoClient
from apps.ingestion.mappers import (
    map_camara_enactment,
    map_camara_events,
    map_camara_proposition,
    map_senado_enactment,
    map_senado_process_events,
    map_senado_process_status,
)
from apps.ingestion.tasks import _enactment_fields, _persist_events
from apps.propositions.activity import invalidate_activity_cache
from apps.propositions.models import Proposition


def refresh_batch(ids):
    results = {}
    changed = []
    with CamaraClient() as camara, SenadoClient() as senado:
        for proposition in Proposition.objects.filter(pk__in=ids).order_by("pk"):
            try:
                if proposition.house == "camara":
                    detail = camara.fetch_detail(proposition.external_id)
                    tramitations = camara.fetch_tramitations(proposition.external_id)
                    mapped = map_camara_proposition({}, detail)
                    fields = {key: mapped[key] for key in ("current_status", "current_status_code")}
                    fields.update(_enactment_fields(map_camara_enactment(detail, tramitations)))
                    events = map_camara_events(tramitations)
                else:
                    process_id = (proposition.raw_payload or {}).get("_senado_process_id")
                    if not process_id:
                        results[str(proposition.pk)] = "missing_process_id"
                        continue
                    process = senado.fetch_process(int(process_id))
                    fields = {
                        **map_senado_process_status(process),
                        **_enactment_fields(map_senado_enactment(process)),
                    }
                    events = map_senado_process_events(process)
                with transaction.atomic():
                    for key, value in fields.items():
                        setattr(proposition, key, value)
                    proposition.save(update_fields=[*fields, "updated_at"])
                    _persist_events(proposition, events)
                results[str(proposition.pk)] = "ok"
                changed.append(proposition)
            except Exception as exc:
                results[str(proposition.pk)] = type(exc).__name__
    if changed:
        invalidate_activity_cache(changed)
    return results
