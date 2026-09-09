from ninja import Router, Schema, Status

from .auth import parliamentarian_enrichment_auth
from .tasks import enrich_parliamentarian_profiles


class EnrichmentRunQueuedSchema(Schema):
    status: str
    task_id: str


router = Router()


@router.post(
    "/parliamentarian-enrichment-runs",
    auth=parliamentarian_enrichment_auth,
    response={202: EnrichmentRunQueuedSchema},
)
def queue_parliamentarian_enrichment(request):
    task = enrich_parliamentarian_profiles.delay()  # type: ignore[attr-defined]
    return Status(202, {"status": "queued", "task_id": task.id})
