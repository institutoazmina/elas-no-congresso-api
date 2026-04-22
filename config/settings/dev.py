from .base import *  # noqa: F403, F401

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Override SES endpoint for local MiniStack
AWS_SES_ENDPOINT_URL = "http://ministack:4566"

# Show queries in development
INSTALLED_APPS += ["django.contrib.admindocs"]  # noqa: F405
