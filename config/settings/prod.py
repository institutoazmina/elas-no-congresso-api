from .base import *  # noqa: F403, F401

DEBUG = False

# AWS_SES_ENDPOINT_URL is None in prod (real SES)
AWS_SES_ENDPOINT_URL = None

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Controlável por env: desligar durante teste HTTP (sem SSL); ligar com domínio/SSL.
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
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
