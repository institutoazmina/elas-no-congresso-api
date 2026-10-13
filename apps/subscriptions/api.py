from hashlib import sha256

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponseRedirect
from ninja import Router
from ninja.errors import HttpError

from apps.core.throttling import subscription_throttle

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


def _reserve_confirmation(email: str) -> bool:
    """Conta um e-mail de confirmação para o endereço, se ainda couber.

    Sem isto qualquer um inscreve o endereço de outra pessoa em loop, enchendo
    a caixa dela com mensagens nossas — e cada reenvio também apagaria o pedido
    pendente legítimo. As chaves usam o hash para não guardar e-mails no Redis.
    """
    digest = sha256(email.strip().lower().encode()).hexdigest()
    cooldown_key = f"subscriptions:confirmation:cooldown:{digest}"
    daily_key = f"subscriptions:confirmation:daily:{digest}"

    if not cache.add(
        cooldown_key, True, timeout=settings.SUBSCRIPTION_CONFIRMATION_COOLDOWN_SECONDS
    ):
        return False
    cache.add(daily_key, 0, timeout=24 * 60 * 60)
    return cache.incr(daily_key) <= settings.SUBSCRIPTION_CONFIRMATIONS_PER_DAY


@router.post("", response={201: list[SubscriptionSchema]}, throttle=[subscription_throttle])
def create_subscription(request, payload: SubscriptionCreateSchema):
    from .service import register_subscriptions
    from .tasks import send_confirmation_email

    if not _reserve_confirmation(payload.email):
        raise HttpError(
            429, "Já enviamos uma confirmação para este e-mail. Confira sua caixa de entrada."
        )

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
