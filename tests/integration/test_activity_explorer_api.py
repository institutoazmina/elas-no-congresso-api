import csv
from datetime import date, timedelta
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


@pytest.fixture
def year_range_data(activity_data, monkeypatch):
    years = {
        activity_data["missing"].pk: 2020,
        activity_data["shared"].pk: 2021,
        activity_data["older"].pk: 2022,
        activity_data["institutional"].pk: 2023,
    }
    source = [
        {**item, "presented_at": date(years[item["id"]], 6, 15)}
        for item in explorer._all_activity()
    ]
    monkeypatch.setattr(explorer, "_all_activity", lambda: source)
    return activity_data


@pytest.mark.parametrize(
    ("params", "years"),
    [
        ({}, {2020, 2021, 2022, 2023}),
        ({"year_start": 2021}, {2021, 2022, 2023}),
        ({"year_end": 2022}, {2020, 2021, 2022}),
        ({"year_start": 2021, "year_end": 2022}, {2021, 2022}),
        ({"year_start": 2021, "year_end": 2021}, {2021}),
        ({"year_start": "", "year_end": ""}, {2020, 2021, 2022, 2023}),
        ({"year_start": 2021, "year_end": ""}, {2021, 2022, 2023}),
        ({"year_start": "", "year_end": 2022}, {2020, 2021, 2022}),
        ({"year_start": 2024}, set()),
        ({"year_end": 2019}, set()),
        ({"year": 2022}, {2022}),
    ],
)
def test_inclusive_year_ranges_and_open_ends(year_range_data, params, years):
    result = get_explorer(**params)
    assert result["total"] == len(years)
    assert {int(item["presented_at"][:4]) for item in result["items"]} == years
    assert result["summary"]["active_filter_count"] == int(bool(years != {2020, 2021, 2022, 2023}))
    assert [option["value"] for option in result["options"]["year"]] == [
        "2023",
        "2022",
        "2021",
        "2020",
    ]


def test_year_range_summary_dashboard_and_export_cover_all_pages(year_range_data):
    params = {"year_start": 2021, "year_end": 2022, "page_size": 1}
    result = get_explorer(**params)
    assert result["total"] == 2
    assert result["page_count"] == 2
    assert len(result["items"]) == 1
    assert result["summary"] == {
        "favorable": 1,
        "unfavorable": 1,
        "favorable_share": 50.0,
        "active_filter_count": 1,
    }
    assert result["dashboard"]["house"][0]["favorable"] == 1
    assert result["dashboard"]["house"][0]["unfavorable"] == 1
    second = get_explorer(**params, page=2)
    assert second["summary"] == result["summary"]
    assert second["items"][0]["id"] != result["items"][0]["id"]
    response = Client().get("/api/v1/activity/explorer/export", params)
    assert response.status_code == 200
    rows = list(csv.reader(StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
    assert {int(row[2]) for row in rows[1:]} == {2021, 2022}
    assert len(rows) == 3


def test_year_range_combines_with_religion_and_legacy_year(year_range_data):
    result = get_explorer(year_start=2022, year_end=2023, religion="Católica")
    assert [item["id"] for item in result["items"]] == [year_range_data["older"].pk]
    assert result["summary"]["active_filter_count"] == 2
    exact = get_explorer(year=2022, year_start=2021, year_end=2023)
    assert exact["total"] == 1
    assert exact["summary"]["active_filter_count"] == 1


@pytest.mark.parametrize(
    "params",
    [
        {"year_start": 2023, "year_end": 2021},
        {"year_start": "invalid"},
        {"year_end": "invalid"},
        {"year_start": 0},
        {"year_end": 10000},
    ],
)
def test_invalid_year_ranges_return_validation_error(params):
    for endpoint in ("/api/v1/activity/explorer", "/api/v1/activity/explorer/export"):
        assert Client().get(endpoint, params).status_code == 422


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


def test_pl_author_filters_can_match_different_coauthors(activity_data):
    assert get_explorer(religion="Católica", gender="M")["total"] == 1
    assert get_explorer(religion="Católica", state="BA")["total"] == 1
    assert get_explorer(religion="Evangélica", gender="M", state="BA")["total"] == 1


def test_other_proposition_types_keep_same_signer_matching(activity_data):
    shared = activity_data["shared"]
    shared.type_code = "PEC"
    shared.save(update_fields=["type_code"])
    assert get_explorer(religion="Católica", gender="M")["total"] == 0
    assert get_explorer(religion="Católica", state="BA")["total"] == 0
    assert get_explorer(religion="Evangélica", gender="M", state="BA")["total"] == 1


@pytest.fixture
def multiple_filter_data(activity_data):
    older = activity_data["older"]
    older.presented_at = timezone.localdate() - timedelta(days=200)
    older.save(update_fields=["presented_at"])
    annotation = older.annotations.get()
    annotation.category = "educacao_cultura"
    annotation.save(update_fields=["category"])
    return activity_data


@pytest.mark.parametrize(
    ("name", "values", "matching"),
    [
        ("party", ["PT", "PL"], ["shared", "older"]),
        ("religion", ["Católica", "Evangélica"], ["shared", "older"]),
        ("religion", ["Evangélica", "__unknown__"], ["shared", "missing"]),
        ("state", ["SP", "RJ"], ["shared", "older", "missing"]),
        ("celerity", ["Rápida", "Travada"], ["shared", "older", "institutional"]),
        ("category", ["saude", "educacao_cultura"], ["shared", "older"]),
        ("evaluator", ["AzMina", "Themis"], ["shared", "older"]),
    ],
)
def test_repeated_filter_values_match_any_selected_option(
    multiple_filter_data, name, values, matching
):
    result = get_explorer(**{name: values})
    assert {item["id"] for item in result["items"]} == {
        multiple_filter_data[key].pk for key in matching
    }
    assert result["total"] == len(matching)
    # Several values in one control count as one active filter.
    assert result["summary"]["active_filter_count"] == 1


@pytest.mark.parametrize(
    ("name", "value", "matching"),
    [
        ("party", "PT", ["shared", "older"]),
        ("religion", "catolica", ["shared", "older"]),
        ("state", "SP", ["shared", "older"]),
        ("celerity", "Rápida", ["shared", "institutional"]),
        ("category", "saude", ["shared"]),
        ("evaluator", "azmina", ["shared"]),
    ],
)
def test_multiple_filters_preserve_legacy_scalars_and_ignore_blank_duplicates(
    multiple_filter_data, name, value, matching
):
    legacy = get_explorer(**{name: value})
    multiple = get_explorer(**{name: ["", f" {value} ", value, "does-not-exist"]})
    expected = {multiple_filter_data[key].pk for key in matching}
    assert {item["id"] for item in legacy["items"]} == expected
    assert {item["id"] for item in multiple["items"]} == expected
    assert multiple["total"] == len(expected)
    assert multiple["summary"]["active_filter_count"] == 1
    assert get_explorer(**{name: ["", " "]})["summary"]["active_filter_count"] == 0


def test_multiple_values_combine_with_and_and_keep_coauthor_dashboards(multiple_filter_data):
    params = {
        "party": ["PT", "nonexistent"],
        "state": ["BA", "RJ"],
        "religion": ["catolica", "nonexistent"],
        "category": ["saude", "educacao_cultura"],
        "evaluator": ["AzMina", "Themis"],
        "celerity": ["Rápida", "Travada"],
        "author_minimum": 1,
    }
    result = get_explorer(**params)
    assert [item["id"] for item in result["items"]] == [multiple_filter_data["shared"].pk]
    assert result["summary"]["active_filter_count"] == 6
    # Católica comes from Álice, BA from Bruno; both contributors appear once.
    assert {row["label"] for row in result["dashboard"]["author"]} == {"Álice Silva", "Bruno Souza"}
    assert all(row["favorable"] == 1 for row in result["dashboard"]["author"])
    assert get_explorer(**{**params, "party": ["nonexistent"]})["total"] == 0


def test_multiple_values_share_pagination_summary_and_export(multiple_filter_data):
    params = {
        "religion": ["Católica", "Evangélica"],
        "category": ["saude", "educacao_cultura"],
        "evaluator": ["AzMina", "Themis"],
        "page_size": 1,
        "sort": "number",
        "direction": "ascending",
    }
    first = get_explorer(**params)
    second = get_explorer(**params, page=2)
    assert first["total"] == first["page_count"] == 2
    assert first["summary"] == second["summary"]
    assert first["dashboard"] == second["dashboard"]
    assert {first["items"][0]["id"], second["items"][0]["id"]} == {
        multiple_filter_data["shared"].pk,
        multiple_filter_data["older"].pk,
    }
    response = Client().get("/api/v1/activity/explorer/export", params)
    assert response.status_code == 200
    rows = list(csv.reader(StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
    assert [row[0] for row in rows[1:]] == ["PL 2/2026", "PL 10/2026"]


def test_multiple_evaluator_and_category_filters_use_only_displayed_assessment(activity_data):
    shared = activity_data["shared"]
    themis = AssessmentOrganization.objects.get(name="Themis")
    PropositionAnnotation.objects.create(
        proposition=shared, organization=themis, is_favorable=False, category="educacao_cultura"
    )
    displayed = get_explorer(
        evaluator=["Themis", "unavailable"], category=["educacao_cultura", "unavailable"]
    )
    assert [item["id"] for item in displayed["items"]] == [shared.pk]
    assert displayed["items"][0]["assessment_organization"] == "Themis"
    assert shared.pk not in [
        item["id"] for item in get_explorer(evaluator=["AzMina", "unavailable"])["items"]
    ]
    assert shared.pk not in [
        item["id"] for item in get_explorer(category=["saude", "unavailable"])["items"]
    ]


def test_option_names_containing_commas_are_not_split(activity_data):
    organization = activity_data["shared"].annotations.get().organization
    organization.name = "Instituto Mulher, Política e Sociedade"
    organization.save(update_fields=["name"])
    cache.clear()
    result = get_explorer(evaluator=[organization.name, "Themis"])
    assert result["total"] == 2


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
    legislature, _ = Legislature.objects.get_or_create(
        number=57, defaults={"start_date": "2023-02-01", "end_date": "2027-01-31"}
    )
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


def test_flat_source_matches_legacy_without_hydrating_models(
    activity_data, django_assert_num_queries
):
    from unittest.mock import patch

    from apps.propositions.activity import _queryset, _serialize
    from apps.propositions.explorer_source import load_explorer_source
    from apps.propositions.models import PropositionAnalysis
    from apps.taxonomy.models import PropositionTheme, Theme

    shared = activity_data["shared"]
    shared.full_text = "Unused document body " * 1000
    shared.raw_payload = {"unused": "large official payload"}
    shared.save(update_fields=["full_text", "raw_payload"])
    theme = Theme.objects.create(slug="projection-test", name="Tema preservado")
    PropositionTheme.objects.create(proposition=shared, theme=theme)
    PropositionAnalysis.objects.create(
        proposition=activity_data["missing"],
        analysis_status="succeeded",
        classification=0,
        theme_category="saude",
        theme_scores={"unused": 0.99},
    )
    organization = AssessmentOrganization.objects.get(name="Themis")
    PropositionAnnotation.objects.create(
        proposition=shared,
        organization=organization,
        is_favorable=False,
        category="educacao_cultura",
        comments="Prevalece sobre favorável",
    )
    expected = [_serialize(p, event_limit=0) for p in _queryset().order_by("-presented_at", "-pk")]
    # from_db catches all accidental model materialization, not only N+1 SQL.
    with (
        patch("django.db.models.Model.from_db", side_effect=AssertionError("ORM hydration")),
        django_assert_num_queries(6),  # source records, transfers, events, annotations, authors, themes
    ):
        actual = load_explorer_source()
    assert actual == expected


@pytest.mark.parametrize("days", [0, 89, 90, 179, 180, 359, 360])
def test_event_aggregates_preserve_celerity_boundaries(activity_data, days):
    from datetime import UTC, datetime, time

    from apps.propositions.activity import _queryset, _serialize
    from apps.propositions.explorer_source import load_explorer_source

    proposition = activity_data["older"]
    day = timezone.localdate() - timedelta(days=days)
    PropositionEvent.objects.bulk_create(
        [
            PropositionEvent(
                proposition=proposition, event_at=datetime.combine(day, time.min, UTC)
            ),
            PropositionEvent(
                proposition=proposition, event_at=datetime.combine(day, time(0, 1), UTC)
            ),
            PropositionEvent(
                proposition=proposition, event_at=datetime.combine(day, time(23, 59), UTC)
            ),
            # A more recent administrative event cannot alter the label or count.
            PropositionEvent(proposition=proposition, event_at=timezone.now(), is_countable=False),
        ]
    )
    expected = _serialize(_queryset().get(pk=proposition.pk), event_limit=0)
    actual = next(item for item in load_explorer_source() if item["id"] == proposition.pk)
    assert actual["celerity"] == expected["celerity"]


def test_projection_queries_exclude_heavy_columns(activity_data):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from apps.propositions.explorer_source import load_explorer_source

    with CaptureQueriesContext(connection) as queries:
        load_explorer_source()
    sql = "\n".join(query["sql"] for query in queries)
    for column in ("full_text", "raw_payload", "theme_scores", "favorability_scores", "bio"):
        assert f'"{column}"' not in sql
    events_sql = next(
        query["sql"] for query in queries if 'FROM "proposition_events"' in query["sql"]
    )
    assert "COUNT(" in events_sql and "MAX(" in events_sql
    assert '"description"' not in events_sql
    assert '"dispatch"' not in events_sql


def test_prepared_source_keeps_search_and_options_without_rebuilding(activity_data):
    from unittest.mock import patch

    first = get_explorer(search="alice")
    with (
        patch.object(explorer, "_options", side_effect=AssertionError("options rebuilt")),
        patch.object(explorer, "_search_text", side_effect=AssertionError("search rebuilt")),
        patch.object(explorer, "load_explorer_source", side_effect=AssertionError("DB rebuilt")),
    ):
        second = get_explorer(search="alice", page_size=1)
    assert first["options"] == second["options"]
    assert first["total"] == second["total"]
    assert second["items"][0]["id"] == first["items"][0]["id"]
    assert "_search" not in second["items"][0]


def test_prepared_source_expires_at_local_midnight(activity_data, monkeypatch):
    source = explorer._all_activity()
    original = source.built_on
    monkeypatch.setattr(timezone, "localdate", lambda: original + timedelta(days=1))
    refreshed = explorer._all_activity()
    assert refreshed.built_on == original + timedelta(days=1)
    by_id = {item["id"]: item for item in source}
    for item in refreshed:
        assert item["celerity"]["days_without_movement"] == (
            by_id[item["id"]]["celerity"]["days_without_movement"] + 1
        )
