from ninja import ModelSchema

from .models import Legislature, Parliamentarian, Party

PARLIAMENTARIAN_DETAIL_FIELDS = [
    "id",
    "full_name",
    "social_name",
    "photo_url",
    "gender",
    "birth_date",
    "race",
    "education",
    "birthplace",
    "profession",
    "religion",
    "bio",
]


class LegislatureSchema(ModelSchema):
    class Meta:
        model = Legislature
        fields = ["number", "start_date", "end_date"]


class PartySchema(ModelSchema):
    class Meta:
        model = Party
        fields = ["id", "acronym", "name", "ideology"]


class ParliamentarianSchema(ModelSchema):
    class Meta:
        model = Parliamentarian
        fields = ["id", "full_name", "social_name", "photo_url", "gender"]


class ParliamentarianDetailSchema(ModelSchema):
    class Meta:
        model = Parliamentarian
        fields = PARLIAMENTARIAN_DETAIL_FIELDS
