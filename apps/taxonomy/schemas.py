
from ninja import ModelSchema, Schema

from .models import AnalyticalTag, Theme


class CategorySchema(Schema):
    """`value` é o token que o matcher de alertas usa; `label`, o rótulo."""

    value: str
    label: str


class ThemeSchema(ModelSchema):
    class Meta:
        model = Theme
        fields = ["id", "slug", "name"]


class AnalyticalTagSchema(ModelSchema):
    class Meta:
        model = AnalyticalTag
        fields = ["id", "slug", "name", "description"]
