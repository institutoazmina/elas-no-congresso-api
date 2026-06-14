from django.apps import AppConfig


class IngestionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ingestion"
    verbose_name = "Coleta de dados"

    def ready(self):
        from . import signals  # noqa: F401
