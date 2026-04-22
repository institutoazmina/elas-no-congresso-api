import secrets

from django.db import models


def _generate_token():
    return secrets.token_urlsafe(48)


class Subscription(models.Model):
    email = models.EmailField(db_index=True)
    ast = models.JSONField()
    # TSQUERY stored as text, cast to tsquery in raw SQL queries
    query = models.TextField()
    needs_revalidation = models.BooleanField(default=False)
    is_active = models.BooleanField(default=False)
    confirm_token = models.CharField(max_length=64, unique=True, default=_generate_token)
    unsubscribe_token = models.CharField(max_length=64, unique=True, default=_generate_token)
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "subscriptions"
        indexes = [
            models.Index(fields=["is_active"], name="ix_subs_active"),
        ]

    def __str__(self):
        return f"{self.email} ({'ativa' if self.is_active else 'pendente'})"
