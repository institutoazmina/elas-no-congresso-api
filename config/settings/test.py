import os
from urllib.parse import urlparse

from .base import *  # noqa: F403, F401


def _url_to_dict(url: str) -> dict:
    parsed = urlparse(url)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": parsed.username,
        "PASSWORD": parsed.password,
        "HOST": parsed.hostname,
        "PORT": parsed.port or 5432,
    }


DEBUG = False

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")

if TEST_DB_URL:
    db_parts = _url_to_dict(TEST_DB_URL)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": db_parts["NAME"],
            "USER": db_parts["USER"],
            "PASSWORD": db_parts["PASSWORD"],
            "HOST": db_parts["HOST"],
            "PORT": db_parts["PORT"],
            "CONN_MAX_AGE": 0,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": "legislativo_test",
            "USER": "elas",
            "PASSWORD": "elas",
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 0,
        }
    }

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

AWS_SES_ENDPOINT_URL = "http://localhost:4566"
ANYMAIL["AMAZON_SES_CLIENT_PARAMS"]["endpoint_url"] = AWS_SES_ENDPOINT_URL  # noqa: F405

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]
