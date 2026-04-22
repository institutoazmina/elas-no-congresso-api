
from ninja import ModelSchema

from .models import Proposition


class PropositionSchema(ModelSchema):
    class Meta:
        model = Proposition
        exclude = ["raw_payload"]


class PropositionDetailSchema(ModelSchema):
    class Meta:
        model = Proposition
        exclude = ["raw_payload"]
