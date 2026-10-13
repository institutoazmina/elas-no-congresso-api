"""Limites de requisição por cliente para a API pública.

Em produção o tráfego chega pelo Cloudflare Tunnel: ``REMOTE_ADDR`` é sempre o
gateway do Docker e ``X-Forwarded-For`` traz o que o cliente quiser prefixar —
o throttle padrão do Ninja usa esse cabeçalho inteiro como identidade, então um
valor aleatório por requisição bastava para ganhar uma cota nova. O único
endereço confiável é o ``CF-Connecting-IP``, que o Cloudflare sobrescreve.
"""

from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest
from ninja.throttling import AnonRateThrottle


def client_ip(request: HttpRequest) -> str | None:
    """Endereço do cliente. ``CF-Connecting-IP`` só vale quando a origem é
    alcançável apenas pelo Cloudflare; fora disso o cabeçalho é forjável."""
    if settings.TRUST_CF_CONNECTING_IP:
        forwarded = request.META.get("HTTP_CF_CONNECTING_IP", "").strip()
        if forwarded:
            return forwarded
    return request.META.get("REMOTE_ADDR")


class ClientRateThrottle(AnonRateThrottle):
    """Throttle por IP com escopo próprio e taxa lida do settings a cada request.

    O escopo separa as cotas no cache: sem ele o limite global e o de uma rota
    dividiriam a mesma chave. Ler a taxa na hora deixa ``settings`` (env,
    testes) valer sem reimportar os routers.
    """

    def __init__(self, scope: str, rate: Callable[[], str]):
        self.scope = scope
        self._rate = rate

    def allow_request(self, request: HttpRequest) -> bool:
        self.rate = self._rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request)

    def get_ident(self, request: HttpRequest) -> str | None:
        return client_ip(request)


def setting_rate(name: str) -> Callable[[], str]:
    return lambda: getattr(settings, name)


api_throttle = ClientRateThrottle("api", setting_rate("API_THROTTLE_RATE"))
export_throttle = ClientRateThrottle("export", setting_rate("EXPORT_THROTTLE_RATE"))
dataset_download_throttle = ClientRateThrottle(
    "dataset-download", setting_rate("DATASET_DOWNLOAD_THROTTLE_RATE")
)
subscription_throttle = ClientRateThrottle(
    "subscription", lambda: f"{settings.SUBSCRIPTION_THROTTLE_RATE_PER_HOUR}/h"
)
