from decouple import config

from .base import *  # noqa: F403, F401

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Desenvolvimento usa Mailpit via SMTP; produção continua com SES.
EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = config("EMAIL_HOST", default="localhost")
EMAIL_PORT = config("EMAIL_PORT", default=1025, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=False, cast=bool)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")

# Show queries in development
INSTALLED_APPS += ["django.contrib.admindocs"]  # noqa: F405
