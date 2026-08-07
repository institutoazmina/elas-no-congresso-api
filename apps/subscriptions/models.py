import secrets

from django.db import models


def _generate_token():
    return secrets.token_urlsafe(48)


class Frequency(models.TextChoices):
    WEEKLY = "weekly", "Semanal"
    DAILY = "daily", "Diário"


class Subscription(models.Model):
    email = models.EmailField(db_index=True)
    frequency = models.CharField(
        max_length=10, choices=Frequency.choices, default=Frequency.DAILY
    )
    ast = models.JSONField()
    # TSQUERY stored as text, cast to tsquery in raw SQL queries
    query = models.TextField()
    needs_revalidation = models.BooleanField(default=False)
    is_active = models.BooleanField(default=False)
    confirm_token = models.CharField(max_length=64, unique=True, default=_generate_token)
    unsubscribe_token = models.CharField(max_length=64, unique=True, default=_generate_token)
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    # LGPD: quando a pessoa marcou o aceite dos termos no modal.
    accepted_terms_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "subscriptions"
        indexes = [
            models.Index(fields=["is_active"], name="ix_subs_active"),
        ]

    def __str__(self):
        return f"{self.email} ({'ativa' if self.is_active else 'pendente'})"


class AlertDelivery(models.Model):
    """Registro de "já avisei esta inscrição sobre esta proposição".

    O match roda em mais de um gatilho (a proposição entra, depois a anotação
    humana chega e muda o que ela casa). O unique é o que garante um e-mail só.
    """

    subscription = models.ForeignKey(
        Subscription, on_delete=models.CASCADE, related_name="deliveries"
    )
    proposition = models.ForeignKey(
        "propositions.Proposition", on_delete=models.CASCADE, related_name="alert_deliveries"
    )
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "alert_deliveries"
        constraints = [
            models.UniqueConstraint(
                fields=["subscription", "proposition"], name="alert_deliveries_sub_prop"
            )
        ]
