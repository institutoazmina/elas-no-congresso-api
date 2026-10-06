import json
from datetime import datetime
from pathlib import Path

from celery.schedules import crontab
from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config("SECRET_KEY", default="django-insecure-changeme-in-prod")


def _tse_archive_urls(value):
    if not isinstance(value, dict):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("TSE_CANDIDATES_ARCHIVE_URLS must be a JSON object")
    return {int(year): str(url) for year, url in value.items()}


TSE_CANDIDATES_ARCHIVE_URLS = config(
    "TSE_CANDIDATES_ARCHIVE_URLS",
    default=json.dumps(
        {
            "2018": "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2018.zip",
            "2022": "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2022.zip",
        }
    ),
    cast=_tse_archive_urls,
)

SENADO_FRONT_CATALOG_URL = (
    "https://www25.senado.leg.br/web/atividade/conselhos/-/conselho/frentes-parlamentares"
)
SENADO_FRONT_MAX_BYTES = 2 * 1024 * 1024
SENADO_FRONT_MAX_PAGES = 200
SENADO_FRONT_MAX_FRONTS = 100
SENADO_FRONT_MAX_REDIRECTS = 3

DEBUG = config("DEBUG", default=True, cast=bool)

ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="*", cast=Csv())

DJANGO_APPS = [
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "unfold.contrib.inlines",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
]

THIRD_PARTY_APPS = [
    "anymail",
    "corsheaders",
    "django_celery_beat",
    "django_celery_results",
]

LOCAL_APPS = [
    "apps.core",
    "apps.legislatures",
    "apps.propositions",
    "apps.taxonomy",
    "apps.committees",
    "apps.activity",
    "apps.norms",
    "apps.subscriptions",
    "apps.ingestion",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    # First: rewrite Host on health paths so orchestrator probes bypass
    # ALLOWED_HOSTS (kamal-proxy uses the container ID as Host).
    "config.middleware.HealthCheckHostMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Antes do CommonMiddleware, como manda o django-cors-headers: o preflight
    # precisa de resposta antes de qualquer redirect de APPEND_SLASH.
    "corsheaders.middleware.CorsMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("POSTGRES_DB", default="elas"),
        "USER": config("POSTGRES_USER", default="elas"),
        "PASSWORD": config("POSTGRES_PASSWORD", default="elas"),
        "HOST": config("POSTGRES_HOST", default="localhost"),
        "PORT": config("POSTGRES_PORT", default="5432"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"connect_timeout": 10},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Django 5.1 removed STATICFILES_STORAGE; use STORAGES. WhiteNoise compressed
# manifest = hashed + gzipped assets with far-future caching.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Cache (Redis)
REDIS_URL = config("REDIS_URL", default="redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
        "TIMEOUT": 300,
    }
}

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"

# Celery
CELERY_BROKER_URL = config("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = "django-db"
CELERY_CACHE_BACKEND = "default"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
# Task longo (backfill de anotações ~2-3h) + acks_late no broker Redis: sem isto,
# o broker re-entrega a mensagem após 1h (visibility_timeout padrão) e o task
# rodaria de novo. Estende a janela para além da duração da carga.
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 6 * 60 * 60}  # 6h
CELERY_TASK_COMPRESSION = "gzip"
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TASK_ROUTES = {
    "apps.ingestion.tasks.classify_proposition": {"queue": "ml"},
}

# Horário local (America/Sao_Paulo), configurável no ambiente do worker e beat.
DAILY_DIGEST_TIME = config(
    "DAILY_DIGEST_TIME",
    default="09:00",
    cast=lambda value: datetime.strptime(value, "%H:%M").time(),
)

# QuitérIA 2.0: os artefatos são baixados na imagem de runtime e carregados
# apenas pelo worker da fila ``ml``. A revisão é fixa para que um deploy seja
# reprodutível mesmo se o repositório do Hub receber novos pesos.
QUITERIA_ENABLED = config("QUITERIA_ENABLED", default=True, cast=bool)
QUITERIA_MODEL_DIR = config("QUITERIA_MODEL_DIR", default="/models/quiteria-2.0")
QUITERIA_MODEL_ID = "azmina/quiteria-2.0"
QUITERIA_MODEL_REVISION = "6f258ee80c0ac410ce60317a4e31460590d7e594"
QUITERIA_FAVORABILITY_THRESHOLD = config(
    "QUITERIA_FAVORABILITY_THRESHOLD", default=0.2254, cast=float
)

# Coleta diária (DatabaseScheduler sincroniza este dict para o banco no startup).
CELERY_BEAT_SCHEDULE = {
    "enrich-parliamentarian-profiles-daily": {
        "task": "apps.ingestion.tasks.enrich_parliamentarian_profiles",
        "schedule": crontab(hour=3, minute=0),
    },
    "ingest-camara-daily": {
        "task": "apps.ingestion.tasks.ingest_camara",
        "schedule": crontab(hour=6, minute=0),
    },
    "ingest-senado-daily": {
        "task": "apps.ingestion.tasks.ingest_senado",
        "schedule": crontab(hour=6, minute=10),
    },
    "refresh-enacted-proposition-statuses-daily": {
        "task": "apps.ingestion.tasks.refresh_enacted_proposition_statuses",
        "schedule": crontab(hour=6, minute=30),
    },
    "daily-digest": {
        "task": "apps.subscriptions.tasks.send_daily_digest",
        "schedule": crontab(hour=DAILY_DIGEST_TIME.hour, minute=DAILY_DIGEST_TIME.minute),
    },
    "cleanup-unconfirmed-subscriptions": {
        "task": "apps.subscriptions.tasks.cleanup_unconfirmed_subscriptions",
        "schedule": crontab(hour=4, minute=0),
    },
}

# Public base URL used to build links inside outgoing emails
SITE_BASE_URL = config("SITE_BASE_URL", default="http://localhost:8000")

# Site estático (outro domínio). Usado para o CORS do modal de alertas e para
# devolver o usuário a uma página de verdade depois de confirmar/cancelar.
PUBLIC_SITE_URL = config("PUBLIC_SITE_URL", default="http://localhost:4321")

CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default=(
        "https://www.elasnocongresso.com.br,https://elasnocongresso.com.br,"
        "https://homologacao.elasnocongresso.com.br,http://localhost:4321"
    ),
    cast=Csv(),
)
# O modal faz duas coisas no browser: buscar proposições e postar a inscrição.
# O admin fica de fora — nada com sessão deve responder cross-origin.
CORS_URLS_REGEX = r"^/api/.*$"

# AWS SES
# Em produção, Boto3 obtém credenciais temporárias da instance role do EC2.
# As chaves explícitas só existem para ambientes que não oferecem uma role
# (como o mock SES dos testes).
AWS_ACCESS_KEY_ID = config("AWS_ACCESS_KEY_ID", default=None)
AWS_SECRET_ACCESS_KEY = config("AWS_SECRET_ACCESS_KEY", default=None)
AWS_DEFAULT_REGION = config("AWS_DEFAULT_REGION", default="us-east-1")
AWS_SES_ENDPOINT_URL = config("AWS_SES_ENDPOINT_URL", default=None)
AWS_SES_FROM_EMAIL = config("AWS_SES_FROM_EMAIL", default="alertas@elasnocongresso.local")

# Email via django-anymail (Amazon SES v2 backend). Sem credenciais explícitas,
# Boto3 usa sua credential provider chain (incluindo a instance role do EC2).
# dev/test apontam o cliente SES para um mock e injetam chaves fictícias.
EMAIL_BACKEND = "anymail.backends.amazon_ses.EmailBackend"
DEFAULT_FROM_EMAIL = f"Elas no Congresso <{AWS_SES_FROM_EMAIL}>"
SERVER_EMAIL = DEFAULT_FROM_EMAIL
ANYMAIL = {
    "AMAZON_SES_CLIENT_PARAMS": {
        "region_name": AWS_DEFAULT_REGION,
    },
}
if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
    ANYMAIL["AMAZON_SES_CLIENT_PARAMS"].update(
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )
if AWS_SES_ENDPOINT_URL:
    ANYMAIL["AMAZON_SES_CLIENT_PARAMS"]["endpoint_url"] = AWS_SES_ENDPOINT_URL

# Subscription confirmation token TTL (hours)
SUBSCRIPTION_CONFIRM_TTL_HOURS = 48

# O POST de inscrição é aberto e dispara e-mail pago via SES. Uma pessoa se
# inscreve uma vez; o teto por IP existe só para não virar torneira de spam.
SUBSCRIPTION_THROTTLE_RATE_PER_HOUR = config(
    "SUBSCRIPTION_THROTTLE_RATE_PER_HOUR", default=10, cast=int
)

# django-unfold
UNFOLD = {
    "SITE_TITLE": "Elas no Congresso",
    "SITE_HEADER": "Admin · Elas no Congresso",
    "SITE_URL": "/",
    "SITE_ICON": None,
    "SITE_SYMBOL": "gavel",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
    "COLORS": {
        "primary": {
            "50": "236 253 245",
            "100": "209 250 229",
            "200": "167 243 208",
            "300": "110 231 183",
            "400": "52 211 153",
            "500": "16 185 129",
            "600": "5 150 105",
            "700": "4 120 87",
            "800": "6 95 70",
            "900": "6 78 59",
            "950": "2 44 34",
        },
    },
    "TABS": [],
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": True,
        "navigation": [],
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "%(levelname)s %(asctime)s %(module)s %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "celery": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "apps": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
