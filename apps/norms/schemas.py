from ninja import ModelSchema

from .models import LegalNorm


class LegalNormSchema(ModelSchema):
    class Meta:
        model = LegalNorm
        fields = "__all__"
