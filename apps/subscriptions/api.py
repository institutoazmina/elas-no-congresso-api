from ninja import Router
from ninja.errors import HttpError

from .models import Subscription
from .schemas import SubscriptionCreateSchema, SubscriptionSchema

router = Router()


@router.post("", response={201: SubscriptionSchema})
def create_subscription(request, payload: SubscriptionCreateSchema):
    from .service import register_subscription
    from .tasks import send_confirmation_email

    sub_id = register_subscription(payload.email, payload.ast)
    send_confirmation_email.delay(sub_id)
    sub = Subscription.objects.get(pk=sub_id)
    return 201, sub


@router.post("/confirm/{token}", response={200: SubscriptionSchema})
def confirm_subscription(request, token: str):
    from django.utils import timezone

    try:
        sub = Subscription.objects.get(confirm_token=token, is_active=False)
    except Subscription.DoesNotExist:
        raise HttpError(404, "Token inválido ou já confirmado")

    sub.is_active = True
    sub.confirmed_at = timezone.now()
    sub.save(update_fields=["is_active", "confirmed_at"])
    return sub


@router.delete("/unsubscribe/{token}", response={200: dict})
def unsubscribe(request, token: str):
    try:
        sub = Subscription.objects.get(unsubscribe_token=token)
    except Subscription.DoesNotExist:
        raise HttpError(404, "Token de cancelamento inválido")

    sub.is_active = False
    sub.save(update_fields=["is_active"])
    return {"detail": "Inscrição cancelada com sucesso."}
