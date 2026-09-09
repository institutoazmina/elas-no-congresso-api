from datetime import date

import pytest
from django.db import models

from apps.core.enums import House
from apps.legislatures.models import (
    Legislature,
    Parliamentarian,
    ParliamentarianProfileSource,
    ParliamentarianTerm,
    Party,
)
from apps.legislatures.schemas import ParliamentarianDetailSchema
from apps.legislatures.services.profile_enrichment import (
    ProfileIdentityConflict,
    ProfileIdentityError,
    upsert_source_profile,
)

pytestmark = pytest.mark.django_db


PROFILE_FIELDS = {
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
}


def make_term(*, parliamentarian=None, external_id=42, house=House.CAMARA, legislature=57):
    parliamentarian = parliamentarian or Parliamentarian.objects.create(full_name="Pessoa")
    party = Party.objects.create(acronym=f"P{ParliamentarianTerm.objects.count()}", name="Partido")
    legislature_dates = {
        56: (date(2019, 2, 1), date(2023, 1, 31)),
        57: (date(2023, 2, 1), date(2027, 1, 31)),
    }
    start_date, end_date = legislature_dates[legislature]
    legislature_obj, _ = Legislature.objects.get_or_create(
        number=legislature,
        defaults={"start_date": start_date, "end_date": end_date},
    )
    return ParliamentarianTerm.objects.create(
        parliamentarian=parliamentarian,
        legislature_number=legislature_obj,
        party=party,
        house=house,
        role="Deputado",
        state="SP",
        external_id=external_id,
        start_date=start_date,
    )


def test_detail_schema_is_an_explicit_direct_profile_allowlist():
    assert set(ParliamentarianDetailSchema.Meta.fields) == PROFILE_FIELDS
    assert "created_at" not in ParliamentarianDetailSchema.Meta.fields
    assert "updated_at" not in ParliamentarianDetailSchema.Meta.fields
    assert not any("source" in field for field in ParliamentarianDetailSchema.Meta.fields)


def test_source_profile_table_has_snapshot_shape_and_identity_constraint():
    field_names = {field.name for field in ParliamentarianProfileSource._meta.fields}
    assert {
        "id",
        "parliamentarian",
        "source",
        "source_key",
        "profile_values",
        "source_url",
        "first_seen_at",
        "last_seen_at",
    } <= field_names

    unique_constraints = {
        tuple(constraint.fields)
        for constraint in ParliamentarianProfileSource._meta.constraints
        if isinstance(constraint, models.UniqueConstraint)
    }
    assert ("source", "source_key") in unique_constraints


def test_upsert_creates_snapshot_and_projects_normalized_values():
    parliamentarian = Parliamentarian.objects.create(full_name="Cadastro inicial")
    make_term(parliamentarian=parliamentarian)

    snapshot = upsert_source_profile(
        source="official",
        source_key="42",
        house=House.CAMARA,
        profile_values={
            "external_id": 42,
            "full_name": "Nome oficial",
            "social_name": "Nome público",
            "gender": "F",
            "birthplace": "São Paulo, SP",
            "provenance": "must not be persisted",
        },
        source_url="https://example.test/parliamentarians/42",
    )

    assert snapshot.parliamentarian_id == parliamentarian.id
    assert snapshot.profile_values == {
        "full_name": "Nome oficial",
        "social_name": "Nome público",
        "gender": "F",
        "birthplace": "São Paulo, SP",
    }
    parliamentarian.refresh_from_db()
    assert parliamentarian.full_name == "Nome oficial"
    assert parliamentarian.social_name == "Nome público"
    assert parliamentarian.gender == "F"
    assert parliamentarian.birthplace == "São Paulo, SP"


def test_upsert_is_idempotent_and_refreshes_last_seen():
    parliamentarian = Parliamentarian.objects.create(full_name="Pessoa")
    make_term(parliamentarian=parliamentarian)

    first = upsert_source_profile(
        source="official",
        source_key="42",
        house=House.CAMARA,
        profile_values={"full_name": "Pessoa"},
    )
    first_seen = first.first_seen_at
    second = upsert_source_profile(
        source="official",
        source_key="42",
        house=House.CAMARA,
        profile_values={"full_name": "Pessoa atualizada"},
    )

    assert second.pk == first.pk
    assert ParliamentarianProfileSource.objects.count() == 1
    assert second.first_seen_at == first_seen
    assert second.last_seen_at >= first_seen
    parliamentarian.refresh_from_db()
    assert parliamentarian.full_name == "Pessoa atualizada"


def test_source_none_is_retained_without_clearing_direct_projection():
    parliamentarian = Parliamentarian.objects.create(
        full_name="Pessoa", birthplace="Valor mantido"
    )
    make_term(parliamentarian=parliamentarian)

    snapshot = upsert_source_profile(
        source="official",
        source_key="42",
        house=House.CAMARA,
        profile_values={"birthplace": None},
    )

    assert snapshot.profile_values == {"birthplace": None}
    parliamentarian.refresh_from_db()
    assert parliamentarian.birthplace == "Valor mantido"


def test_source_precedence_is_manual_then_official_then_legacy():
    parliamentarian = Parliamentarian.objects.create(full_name="Cadastro")
    make_term(parliamentarian=parliamentarian, external_id=7)
    make_term(parliamentarian=parliamentarian, external_id=8)
    make_term(parliamentarian=parliamentarian, external_id=9)

    upsert_source_profile(
        source="legacy",
        source_key="7",
        house=House.CAMARA,
        profile_values={"bio": "Bio legada"},
    )
    upsert_source_profile(
        source="official",
        source_key="8",
        house=House.CAMARA,
        profile_values={"bio": "Bio oficial"},
    )
    parliamentarian.refresh_from_db()
    assert parliamentarian.bio == "Bio oficial"

    upsert_source_profile(
        source="manual",
        source_key="9",
        house=House.CAMARA,
        profile_values={"bio": "Bio manual"},
    )
    parliamentarian.refresh_from_db()
    assert parliamentarian.bio == "Bio manual"


def test_upsert_rejects_zero_matching_terms_without_writing_snapshot():
    with pytest.raises(ProfileIdentityError):
        upsert_source_profile(
            source="official",
            source_key="404",
            house=House.CAMARA,
            profile_values={"full_name": "Sem termo"},
        )

    assert ParliamentarianProfileSource.objects.count() == 0


def test_upsert_rejects_ambiguous_term_assignment_without_writing_snapshot():
    first = Parliamentarian.objects.create(full_name="Primeira")
    second = Parliamentarian.objects.create(full_name="Segunda")
    make_term(parliamentarian=first, external_id=77, legislature=57)
    make_term(parliamentarian=second, external_id=77, legislature=56)

    with pytest.raises(ProfileIdentityError):
        upsert_source_profile(
            source="official",
            source_key="77",
            house=House.CAMARA,
            profile_values={"full_name": "Conflito"},
        )

    assert ParliamentarianProfileSource.objects.count() == 0


def test_upsert_accepts_multiple_matching_terms_for_same_parliamentarian():
    parliamentarian = Parliamentarian.objects.create(full_name="Reeleita")
    make_term(parliamentarian=parliamentarian, external_id=77, legislature=57)
    make_term(parliamentarian=parliamentarian, external_id=77, legislature=56)

    snapshot = upsert_source_profile(
        source="official",
        source_key="77",
        house=House.CAMARA,
        profile_values={"full_name": "Nome oficial"},
    )

    assert snapshot.parliamentarian_id == parliamentarian.id
    parliamentarian.refresh_from_db()
    assert parliamentarian.full_name == "Nome oficial"


def test_upsert_rejects_existing_source_assigned_to_another_parliamentarian():
    first = Parliamentarian.objects.create(full_name="Primeira")
    second = Parliamentarian.objects.create(full_name="Segunda")
    make_term(parliamentarian=first, external_id=88)
    make_term(parliamentarian=second, external_id=99)
    ParliamentarianProfileSource.objects.create(
        parliamentarian=second,
        source="official",
        source_key="88",
        profile_values={"full_name": "Segunda"},
    )

    with pytest.raises(ProfileIdentityConflict):
        upsert_source_profile(
            source="official",
            source_key="88",
            house=House.CAMARA,
            profile_values={"full_name": "Primeira"},
        )

    assert ParliamentarianProfileSource.objects.get(source="official", source_key="88").parliamentarian_id == second.id
