import pytest
from django.db.models import UniqueConstraint

from apps.committees.models import (
    Caucus,
    CaucusMembership,
    Committee,
    CommitteeMembership,
    CommitteePresidency,
)
from apps.legislatures.models import ParliamentarianPost
from apps.legislatures.schemas import ParliamentarianDetailSchema

pytestmark = pytest.mark.django_db


PROVENANCE_FIELDS = {
    "source",
    "source_key",
    "source_url",
    "first_seen_at",
    "last_seen_at",
}


def _constraint(model, name):
    return next(constraint for constraint in model._meta.constraints if constraint.name == name)


def _source_key_constraint(model):
    return next(
        constraint
        for constraint in model._meta.constraints
        if isinstance(constraint, UniqueConstraint)
        and tuple(constraint.fields) == ("source", "source_key")
    )


def test_committee_relationship_models_have_nullable_provenance_and_safe_source_identity():
    models = [
        Committee,
        Caucus,
        CommitteeMembership,
        CommitteePresidency,
        CaucusMembership,
    ]

    for model in models:
        fields = {field.name: field for field in model._meta.fields}
        assert fields.keys() >= PROVENANCE_FIELDS
        assert all(fields[name].null for name in PROVENANCE_FIELDS)

        source_key = _source_key_constraint(model)
        assert source_key.condition is not None
        assert source_key.condition.children == [
            ("source__isnull", False),
            ("source_key__isnull", False),
        ]

    assert _constraint(Committee, "committees_house_acronym")
    assert _constraint(Caucus, "caucuses_kind_name_legislature")


def test_membership_dates_allow_unknown_start_without_allowing_reversed_ranges():
    for model, constraint_name in (
        (CommitteeMembership, "cm_date_range"),
        (CommitteePresidency, "cp_date_range"),
        (CaucusMembership, "cau_mem_date_range"),
    ):
        fields = {field.name: field for field in model._meta.fields}
        assert fields["start_date"].null
        assert fields["end_date"].null
        condition = _constraint(model, constraint_name).condition
        assert condition is not None
        assert any(lookup == "end_date__gte" for lookup, _ in condition.children)


def test_caucus_has_house_effectivity_and_observation_state_without_changing_natural_key():
    fields = {field.name: field for field in Caucus._meta.fields}
    assert {"house", "start_date", "end_date", "is_active"} <= fields.keys()
    assert fields["house"].null
    assert fields["start_date"].null
    assert fields["end_date"].null
    assert fields["is_active"].null
    assert _constraint(Caucus, "caucuses_kind_name_legislature")
    date_condition = _constraint(Caucus, "caucus_date_range").condition
    assert any(lookup == "end_date__gte" for lookup, _ in date_condition.children)


def test_committee_relationships_keep_unknown_dates_and_add_optional_legislature_observation():
    for model in (CommitteeMembership, CommitteePresidency):
        fields = {field.name: field for field in model._meta.fields}
        assert {"legislature", "is_observed_current"} <= fields.keys()
        assert fields["legislature"].null
        assert fields["is_observed_current"].null

    caucus_membership_fields = {field.name: field for field in CaucusMembership._meta.fields}
    assert "legislature" not in caucus_membership_fields
    assert caucus_membership_fields["is_observed_current"].null


def test_parliamentarian_post_has_institutional_effectivity_and_provenance_shape():
    fields = {field.name: field for field in ParliamentarianPost._meta.fields}

    assert {
        "id",
        "parliamentarian",
        "house",
        "legislature",
        "title",
        "organization_name",
        "start_date",
        "end_date",
        "is_observed_current",
        *PROVENANCE_FIELDS,
    } <= fields.keys()
    assert fields["legislature"].null
    assert fields["organization_name"].null
    assert fields["start_date"].null
    assert fields["end_date"].null
    assert "organization" not in fields
    assert "observation_state" not in fields
    assert fields["is_observed_current"].null
    assert not fields["source"].null
    assert not fields["source_key"].null
    assert fields["source_url"].null
    assert not fields["first_seen_at"].null
    assert not fields["last_seen_at"].null
    assert fields["first_seen_at"].auto_now_add
    assert fields["last_seen_at"].auto_now

    source_key = _source_key_constraint(ParliamentarianPost)
    assert source_key.condition is None
    date_condition = _constraint(ParliamentarianPost, "parliamentarian_posts_date_range").condition
    assert any(lookup == "end_date__gte" for lookup, _ in date_condition.children)

    index_fields = {tuple(index.fields) for index in ParliamentarianPost._meta.indexes}
    assert ("parliamentarian", "legislature", "start_date") in index_fields
    assert ("house", "legislature", "is_observed_current") in index_fields


def test_public_parliamentarian_detail_schema_remains_direct_profile_only():
    assert "posts" not in ParliamentarianDetailSchema.Meta.fields
    assert not any(field in ParliamentarianDetailSchema.Meta.fields for field in PROVENANCE_FIELDS)
