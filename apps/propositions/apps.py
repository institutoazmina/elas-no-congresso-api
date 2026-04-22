from django.apps import AppConfig


class PropositionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.propositions"
    verbose_name = "Proposições"

    def ready(self):
        import apps.propositions.signals  # noqa: F401
