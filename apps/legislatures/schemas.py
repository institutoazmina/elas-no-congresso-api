from ninja import ModelSchema

from .models import Legislature, Parliamentarian, ParliamentarianTerm, Party

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


class ParliamentarianTermSchema(ModelSchema):
    class Meta:
        model = ParliamentarianTerm
        fields = "__all__"


class ParliamentarianSchema(ModelSchema):
    terms: list[ParliamentarianTermSchema]
    favorable_propositions_count: int
    unfavorable_propositions_count: int

    class Meta:
        model = Parliamentarian
        fields = "__all__"


class ParliamentarianDetailSchema(ModelSchema):
    favorable_propositions_count: int
    unfavorable_propositions_count: int

    class Meta:
        model = Parliamentarian
        fields = PARLIAMENTARIAN_DETAIL_FIELDS
