
from ninja import ModelSchema, Schema

from .models import Subscription


class SubscriptionCreateSchema(Schema):
    email: str
    ast: dict


class SubscriptionSchema(ModelSchema):
    class Meta:
        model = Subscription
        fields = ["id", "email", "is_active", "created_at", "confirmed_at"]
