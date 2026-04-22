from ninja import ModelSchema

from .models import Committee


class CommitteeSchema(ModelSchema):
    class Meta:
        model = Committee
        fields = ["id", "house", "acronym", "name", "kind", "is_active"]
