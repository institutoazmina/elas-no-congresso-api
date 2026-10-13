from decouple import config

from .base import *  # noqa: F403, F401

DEBUG = False

# AWS_SES_ENDPOINT_URL is None in prod (real SES)
AWS_SES_ENDPOINT_URL = None

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# A porta do container só é publicada no docker0 e quem chega nela é o
# cloudflared: o CF-Connecting-IP é o endereço real do cliente.
TRUST_CF_CONNECTING_IP = config("TRUST_CF_CONNECTING_IP", default=True, cast=bool)
# Controlável por env: desligar durante teste HTTP (sem SSL); ligar com domínio/SSL.
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
# O healthcheck interno do kamal-proxy chega via HTTP (sem X-Forwarded-Proto);
# sem isenção, SECURE_SSL_REDIRECT devolve 301 e o container fica "unhealthy".
SECURE_REDIRECT_EXEMPT = [r"^health/"]  # casa health/ e health/ready/

# Django 4+ exige origin (com esquema) p/ POSTs do admin sob HTTPS atrás de proxy.
# Derivado do SITE_BASE_URL (https://api...) — não duplica o domínio em outro lugar.
CSRF_TRUSTED_ORIGINS = [SITE_BASE_URL]  # noqa: F405
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

DATABASES["default"]["CONN_MAX_AGE"] = 60  # noqa: F405
# Verify pooled connections are still alive before reuse (pairs with CONN_MAX_AGE)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True  # noqa: F405
