import secrets

from django.db import models


def _generate_token():
    return secrets.token_urlsafe(48)


class Frequency(models.TextChoices):
    WEEKLY = "weekly", "Semanal"
    DAILY = "daily", "Diário"


class Subscription(models.Model):
    email = models.EmailField(db_index=True)
    frequency = models.CharField(max_length=10, choices=Frequency.choices, default=Frequency.DAILY)
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
    """Proposição incluída em um e-mail enviado com sucesso à inscrição."""

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


class PendingAlert(models.Model):
    """Matches persistidos até o próximo horário do resumo diário."""

    subscription = models.ForeignKey(
        Subscription, on_delete=models.CASCADE, related_name="pending_alerts"
    )
    proposition = models.ForeignKey("propositions.Proposition", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "pending_alerts"
        constraints = [
            models.UniqueConstraint(
                fields=["subscription", "proposition"], name="pending_alerts_sub_prop"
            )
        ]


class DailyDigestDelivery(models.Model):
    """Uma entrega por endereço e data local, inclusive com várias inscrições."""

    email = models.EmailField()
    delivery_date = models.DateField()
    sent_at = models.DateTimeField(null=True, blank=True)
    message_id = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "daily_digest_deliveries"
        constraints = [
            models.UniqueConstraint(
                fields=["email", "delivery_date"], name="daily_digest_email_date"
            )
        ]
