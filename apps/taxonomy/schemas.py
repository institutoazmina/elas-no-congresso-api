
from ninja import ModelSchema

from .models import AnalyticalTag, Theme


class ThemeSchema(ModelSchema):
    class Meta:
        model = Theme
        fields = ["id", "slug", "name"]


class AnalyticalTagSchema(ModelSchema):
    class Meta:
        model = AnalyticalTag
        fields = ["id", "slug", "name", "description"]
