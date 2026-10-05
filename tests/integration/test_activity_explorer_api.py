import csv
from datetime import timedelta
from io import StringIO

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from apps.legislatures.models import (
    InstitutionalAuthor,
    Legislature,
    Parliamentarian,
    ParliamentarianTerm,
    Party,
)
from apps.propositions import explorer
from apps.propositions.models import (
    AssessmentOrganization,
    Proposition,
    PropositionAnnotation,
    PropositionAuthor,
    PropositionEvent,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def activity_data():
    cache.clear()
    alice = Parliamentarian.objects.create(full_name="Álice Silva", gender="F", religion="Católica")
    bruno = Parliamentarian.objects.create(
        full_name="Bruno Souza", gender="M", religion="Evangélica"
    )
    cara = Parliamentarian.objects.create(full_name="Cara Lima", gender="F", religion="  ")
    unused = Parliamentarian.objects.create(full_name="Sem autoria", religion="Budista")
    pt = Party.objects.create(acronym="PT", name="PT")
    pl = Party.objects.create(acronym="PL", name="PL")
    azmina = AssessmentOrganization.objects.create(name="AzMina")
    themis = AssessmentOrganization.objects.create(name="Themis")
    today = timezone.localdate()

    def proposal(number, **overrides):
        data = {
            "external_id": number,
            "house": "camara",
            "type_code": "PL",
            "number_label": f"PL {number}/2026",
            "number": number,
            "year": 2026,
            "presented_at": today,
            "ementa": "Saúde das mulheres",
            "is_approved": True,
        }
        data.update(overrides)
        return Proposition.objects.create(**data)

    shared = proposal(10)
    older = proposal(2, presented_at=today - timedelta(days=1))
    missing = proposal(3, house="senado", presented_at=today.replace(year=today.year - 1))
    institutional = proposal(4)
    for prop in (shared, older):
        PropositionAuthor.objects.create(
            proposition=prop, parliamentarian=alice, party=pt, state_at_authorship="SP"
        )
    # Duplicate imported authorship rows cannot inflate the dashboards.
    PropositionAuthor.objects.create(
        proposition=shared, parliamentarian=alice, party=pt, state_at_authorship="SP"
    )
    PropositionAuthor.objects.create(
        proposition=shared, parliamentarian=bruno, party=pl, state_at_authorship="BA"
    )
    PropositionAuthor.objects.create(
        proposition=missing, parliamentarian=cara, state_at_authorship="RJ"
    )
    executive = InstitutionalAuthor.objects.create(name="Presidência", kind="executivo")
    PropositionAuthor.objects.create(proposition=institutional, institutional_author=executive)
    PropositionAnnotation.objects.create(
        proposition=shared,
        organization=azmina,
        is_favorable=True,
        category="saude",
        comments="Parecer complementar",
    )
    PropositionAnnotation.objects.create(
        proposition=older, organization=themis, is_favorable=False, category="saude"
    )
    PropositionEvent.objects.create(
        proposition=shared,
        source_event_id="test:one",
        source_kind="tramitation",
        event_at=timezone.now(),
        title="Movimento",
    )
    for number, overrides in [(5, {"is_approved": False}), (6, {"type_code": "REQ"})]:
        hidden = proposal(number, **overrides)
        PropositionAuthor.objects.create(proposition=hidden, parliamentarian=unused)
    yield {
        "alice": alice,
        "bruno": bruno,
        "cara": cara,
        "shared": shared,
        "older": older,
        "missing": missing,
        "institutional": institutional,
        "pt": pt,
    }
    cache.clear()


def get_explorer(**params):
    response = Client().get("/api/v1/activity/explorer", params)
    assert response.status_code == 200, response.content
    return response.json()


def test_religion_facets_only_use_complete_public_collection(activity_data):
    result = get_explorer(religion="Católica", page_size=1)
    assert result["total"] == 2
    assert len(result["items"]) == 1
    assert result["options"]["religion"] == [
        {"value": "Católica", "label": "Católica"},
        {"value": "Evangélica", "label": "Evangélica"},
        {"value": "__unknown__", "label": "Não informada"},
    ]
    assert result["items"][0]["authors"][0]["religion"] == "Católica"
    assert result["options"]["category"] == [{"value": "saude", "label": "Saúde"}]
    assert result["options"]["evaluator"] == [
        {"value": "AzMina", "label": "AzMina"},
        {"value": "Themis", "label": "Themis"},
    ]
    assert result["summary"] == {
        "favorable": 1,
        "unfavorable": 1,
        "favorable_share": 50.0,
        "active_filter_count": 1,
    }


@pytest.mark.parametrize(
    "filters",
    [
        {"search": "alice"},
        {"house": "Deputado"},
        {"year": str(timezone.localdate().year)},
        {"party": "PT"},
        {"category": "saude"},
        {"assessment": "favorable"},
        {"celerity": "Rápida"},
        {"movements": "with"},
        {"gender": "F"},
        {"state": "SP"},
        {"evaluator": "azmina"},
        {"comments": "yes"},
    ],
)
def test_religion_combines_with_existing_filters(activity_data, filters):
    result = get_explorer(religion=" catolica ", **filters)
    assert result["total"] >= 1
    assert activity_data["shared"].pk in [item["id"] for item in result["items"]]
    assert all(
        any(author["religion"] == "Católica" for author in item["authors"])
        for item in result["items"]
    )


def test_combined_author_filters_match_one_signer(activity_data):
    assert get_explorer(religion="Católica", gender="M")["total"] == 0
    assert get_explorer(religion="Católica", state="BA")["total"] == 0
    assert get_explorer(religion="Evangélica", gender="M", state="BA")["total"] == 1


def test_missing_religion_excludes_institutional_authorship(activity_data):
    result = get_explorer(religion="__unknown__")
    assert [item["id"] for item in result["items"]] == [activity_data["missing"].pk]
    empty = get_explorer(religion="No such religion")
    assert empty["total"] == 0
    assert empty["page_count"] == 1
    assert empty["summary"]["favorable_share"] == 0
    assert all(row["color"] == "#998D96" for row in empty["dashboard"]["state"])


def test_dashboard_is_calculated_before_pagination_and_deduplicates_authors(activity_data):
    result = get_explorer(religion="Católica", page_size=1, author_minimum=1)
    dashboard = result["dashboard"]
    assert dashboard["gender"][0]["favorable"] == 1
    assert dashboard["gender"][0]["unfavorable"] == 1
    assert len(dashboard["author"]) == 1
    assert dashboard["author"][0]["label"] == "Álice Silva"
    assert dashboard["party"][0]["label"] == "PT"
    assert dashboard["category"][0]["favorable"] == 1
    assert dashboard["category"][0]["unfavorable"] == 1
    assert dashboard["party"][0]["favorable_width"] == 100
    sp = next(row for row in dashboard["state"] if row["key"] == "SP")
    ba = next(row for row in dashboard["state"] if row["key"] == "BA")
    assert sp["favorable_percent"] == 50
    assert sp["color"] == "#FF5865"
    assert ba["favorable_percent"] is None
    assert get_explorer(religion="Católica", author_minimum=3)["dashboard"]["author"] == []


def test_server_sort_pagination_and_export_use_same_filtered_collection(activity_data):
    result = get_explorer(
        religion="Católica", page_size=1, page=99, sort="number", direction="ascending"
    )
    assert result["page"] == result["page_count"] == 2
    assert result["items"][0]["id"] == activity_data["shared"].pk
    first = get_explorer(religion="Católica", page_size=1, sort="number", direction="ascending")
    assert first["items"][0]["id"] == activity_data["older"].pk
    response = Client().get(
        "/api/v1/activity/explorer/export",
        {
            "religion": "Católica",
            "page_size": 1,
            "page": 99,
            "sort": "number",
            "direction": "ascending",
        },
    )
    assert response.status_code == 200
    assert response["Content-Disposition"] == 'attachment; filename="atividade-legislativa.csv"'
    rows = list(csv.reader(StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
    assert [row[0] for row in rows[1:]] == ["PL 2/2026", "PL 10/2026"]


def test_religion_profile_updates_expire_source_facets_and_details(activity_data):
    alice = activity_data["alice"]
    detail_url = f"/api/v1/activity/{activity_data['older'].pk}"
    assert Client().get(detail_url).json()["authors"][0]["religion"] == "Católica"
    assert get_explorer(religion="Católica")["total"] == 2
    alice.religion = "Judaica"
    alice.save(update_fields=["religion"])
    assert get_explorer(religion="Católica")["total"] == 0
    assert get_explorer(religion="Judaica")["total"] == 2
    assert Client().get(detail_url).json()["authors"][0]["religion"] == "Judaica"


def test_religion_sql_import_expires_activity_cache(activity_data, tmp_path):
    legislature = Legislature.objects.get(pk=57)
    ParliamentarianTerm.objects.create(
        parliamentarian=activity_data["alice"],
        legislature_number=legislature,
        party=activity_data["pt"],
        house="camara",
        role="Deputada",
        state="SP",
        external_id=98765,
        start_date="2023-02-01",
    )
    assert get_explorer(religion="Católica")["total"] == 2
    csv_path = tmp_path / "religions.csv"
    csv_path.write_text("ID_Camara,Identidade Religiosa\n98765,Sem Religião\n", encoding="utf-8")
    call_command("import_parliamentarian_religions", csv_path=csv_path)
    assert get_explorer(religion="Sem Religião")["total"] == 2
    assert get_explorer(religion="Católica")["total"] == 0


def test_explorer_filters_beyond_legacy_5000_limit(activity_data, monkeypatch):
    # A rare matching religion past the old cap must still be selectable and counted.
    source = explorer._all_activity()
    ordinary = next(item for item in source if item["id"] == activity_data["institutional"].pk)
    matching = next(item for item in source if item["id"] == activity_data["older"].pk)
    monkeypatch.setattr(explorer, "_all_activity", lambda: [ordinary] * 5001 + [matching])
    result = get_explorer(religion="Católica")
    assert result["total"] == 1
    assert result["items"][0]["id"] == matching["id"]
    assert {"value": "Católica", "label": "Católica"} in result["options"]["religion"]


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"page_size": 101},
        {"assessment": "bad"},
        {"sort": "bad"},
        {"author_minimum": 0},
    ],
)
def test_explorer_validates_query(params):
    assert Client().get("/api/v1/activity/explorer", params).status_code == 422
