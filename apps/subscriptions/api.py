from django.conf import settings
from django.http import HttpResponseRedirect
from ninja import Router
from ninja.throttling import AnonRateThrottle

from .models import Subscription
from .schemas import SubscriptionCreateSchema, SubscriptionSchema

router = Router()


def _back_to_site(page: str, status: str) -> HttpResponseRedirect:
    """Devolve o usuário ao site estático — o clique veio de um link de e-mail,
    então quem está do outro lado é uma pessoa num browser, não um cliente HTTP."""
    return HttpResponseRedirect(
        f"{settings.PUBLIC_SITE_URL.rstrip('/')}/alertas/{page}?status={status}"
    )


def _back_home(status: str) -> HttpResponseRedirect:
    """A confirmação é o fim do fluxo: devolve a pessoa à página inicial."""
    return HttpResponseRedirect(f"{settings.PUBLIC_SITE_URL.rstrip('/')}/?subscription={status}")


@router.post(
    "",
    response={201: list[SubscriptionSchema]},
    throttle=[AnonRateThrottle(f"{settings.SUBSCRIPTION_THROTTLE_RATE_PER_HOUR}/h")],
)
def create_subscription(request, payload: SubscriptionCreateSchema):
    from .service import register_subscriptions
    from .tasks import send_confirmation_email

    alerts = [alert.dict() for alert in payload.alerts]
    sub_ids = register_subscriptions(payload.email, alerts)
    # Um e-mail só: o token de qualquer uma das linhas confirma o endereço inteiro.
    send_confirmation_email.delay(sub_ids[0])
    return 201, list(Subscription.objects.filter(pk__in=sub_ids))


@router.get("/confirm/{token}", auth=None, include_in_schema=False)
def confirm_subscription(request, token: str):
    from .service import confirm_subscriptions

    # Quem confirma confirma o endereço, não a linha: um clique vale para as
    # duas frequências criadas no mesmo envio.
    return _back_home("confirmado" if confirm_subscriptions(token) else "invalido")


@router.get("/unsubscribe/{token}", auth=None, include_in_schema=False)
def unsubscribe(request, token: str):
    try:
        sub = Subscription.objects.get(unsubscribe_token=token)
    except Subscription.DoesNotExist:
        return _back_to_site("cancelado", "invalido")

    # "Cancelar inscrição" no rodapé do e-mail significa parar de receber —
    # todas as frequências, não só a que gerou aquela mensagem.
    Subscription.objects.filter(email=sub.email).update(is_active=False)
    return _back_to_site("cancelado", "ok")
