from django.apps import AppConfig


class OgConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.og"
    verbose_name = "Imagens de compartilhamento"

    def ready(self):
        import apps.og.signals  # noqa: F401
