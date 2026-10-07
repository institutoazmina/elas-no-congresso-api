from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from apps.legislatures.models import InstitutionalAuthor, Parliamentarian, Party
from apps.newsletters.report import REPORT_TZ, build_snapshot, classify, render, reporting_week
from apps.propositions.models import Proposition, PropositionAuthor, PropositionEvent

START = date(2026, 9, 28)
END = date(2026, 10, 5)


def event(code=None, situation=None, movement=None, committee=None, day=30, house="camara"):
    return SimpleNamespace(
        event_at=datetime(2026, 9, day, 12, tzinfo=REPORT_TZ),
        source_event_id="test",
        raw_payload={"codSituacao" if house == "camara" else "idSituacaoIniciada": code},
        situation=situation,
        title=movement,
        description=movement,
        dispatch=None,
        committee_acronym=committee,
    )


def proposition(**kwargs):
    return SimpleNamespace(house="camara", enacted_at=None, presented_at=date(2020, 1, 1), **kwargs)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (1140, "law"),
        (1150, "law"),
        (1294, "law"),
        (924, "vote"),
        (915, "processing"),
        (925, "processing"),
        (923, "review"),
        (926, "review"),
    ],
)
def test_official_camara_codes(code, expected):
    assert classify(proposition(), [event(code)], START, END)[0] == expected


@pytest.mark.parametrize(
    ("situation", "movement", "expected"),
    [
        ("Aguardando sanção", None, "law"),
        (None, "Encaminhado à sanção presidencial", "law"),
        ("Aguardando designação de relator", None, "processing"),
        (None, "Apresentação do Parecer da Relatora", "vote"),
        (None, "Apresentação do PL 42/2026", "new"),
        ("Arquivada", "Apresentação de parecer", "review"),
        ("Situação desconhecida", None, "review"),
    ],
)
def test_text_rules(situation, movement, expected):
    assert (
        classify(proposition(), [event(situation=situation, movement=movement)], START, END)[0]
        == expected
    )


def test_latest_stage_and_chamber_approval_not_law():
    events = [event(movement="Apresentação do PL", day=28), event(924, day=29), event(915, day=30)]
    assert classify(proposition(), events, START, END)[0] == "processing"
    assert (
        classify(
            proposition(), [event(movement="Aprovado na Câmara", committee="CCJC")], START, END
        )[0]
        == "processing"
    )


def test_reporting_week_uses_calendar_week():
    assert reporting_week(date(2026, 10, 5)) == (START, END)
    assert reporting_week(date(2026, 10, 11)) == (START, END)


def test_render_radar_structure_escaping_and_missing_links():
    def entry(stage, house, number, **extra):
        return {
            "stage": stage,
            "house": house,
            "ementa": "Ementa <script> ![image](file.png)",
            "identifier": f"PDL {number}/2026",
            "url": "",
            "official_status": "Arquivada",
            **extra,
        }

    markdown, html = render(
        [
            entry("new", "camara", 1),
            entry("law", "senado", 2),
            entry("vote", "senado", 3),
            entry("review", "camara", 4),
        ]
    )
    assert (
        markdown.index("PDL 2/2026")
        < markdown.index("Radar da Câmara")
        < markdown.index("Radar do Senado")
    )
    assert markdown.count("PDL 2/2026") == 1
    assert "link oficial a revisar" in markdown
    assert "Status a revisar: Arquivada" in markdown
    assert "<script>" not in html and "<img" not in html
    assert "Nenhuma movimentação" in render([])[0]
    assert "Coleta incompleta" in render([], complete=False)[0]
    assert markdown.count("**Autoria:** não informada.") == 4


@pytest.mark.parametrize("stage,house", [("law", "camara"), ("new", "camara"), ("vote", "senado")])
def test_render_authorship_for_highlights_and_both_radars(stage, house):
    markdown, html = render(
        [
            {
                "stage": stage,
                "house": house,
                "ementa": "Ementa oficial",
                "identifier": "PL 123/2026",
                "url": "https://www.camara.leg.br/propostas-legislativas/123",
                "authors": [
                    {"name": "Ana Silva", "institutional": False, "party": "PSB", "state": "PE"},
                    {"name": "Maria Costa", "institutional": False, "party": None, "state": "SP"},
                    {"name": "Joana Santos", "institutional": False, "party": "PSD", "state": None},
                    {
                        "name": "Comissão <script> ![imagem](url)",
                        "institutional": True,
                        "party": None,
                        "state": None,
                    },
                ],
            }
        ]
    )
    assert (
        "  \n**Autoria:** Ana Silva (PSB–PE); Maria Costa (partido não informado–SP); Joana Santos (PSD–UF não informada); Comissão"
        in markdown
    )
    assert "<br />\n<strong>Autoria:</strong>" in html
    assert "<script>" not in html and "<img" not in html
    assert markdown.count("**Autoria:**") == 1


@pytest.mark.django_db
def test_snapshot_filters_dates_and_preserves_all_tracked():
    def create(number, **extra):
        return Proposition.objects.create(
            house="camara",
            external_id=number,
            type_code="PDL",
            number_label=f"PDL {number}/2020",
            number=number,
            year=2020,
            presented_at=date(2020, 1, 1),
            ementa="Oficial",
            **extra,
        )

    old = create(1, is_approved=False)
    outside = create(2)
    updated_only = create(3)
    new = create(4)
    new.presented_at = START
    new.save()
    party = Party.objects.create(acronym="PSB", name="Partido de teste")
    person = Parliamentarian.objects.create(full_name="Ana Silva", social_name="Ana")
    institution = InstitutionalAuthor.objects.create(name="Comissão de teste", kind="comissao")
    PropositionAuthor.objects.create(
        proposition=old, institutional_author=institution, order_index=2
    )
    PropositionAuthor.objects.create(
        proposition=old,
        parliamentarian=person,
        party=party,
        state_at_authorship="PE",
        order_index=1,
    )
    for prop, at in [
        (old, datetime(2026, 9, 28, 3, tzinfo=UTC)),
        (outside, datetime(2026, 10, 5, 3, tzinfo=UTC)),
    ]:
        PropositionEvent.objects.create(
            proposition=prop,
            event_at=at,
            situation="Pronta para Pauta",
            raw_payload={"codSituacao": 924},
        )
    # A later stage must not leak back into last week's report.
    PropositionEvent.objects.create(
        proposition=old,
        event_at=datetime(2026, 10, 5, 12, tzinfo=REPORT_TZ),
        raw_payload={"codSituacao": 1140},
    )
    snapshot = build_snapshot(START, END)
    assert {entry["id"] for entry in snapshot} == {old.pk, new.pk}
    assert snapshot[0]["stage"] == "vote"
    assert snapshot[0]["is_approved"] is False
    assert updated_only.pk not in {entry["id"] for entry in snapshot}
    assert snapshot[0]["authors"] == [
        {"name": "Ana", "institutional": False, "party": "PSB", "state": "PE"},
        {"name": "Comissão de teste", "institutional": True, "party": None, "state": None},
    ]
    party.acronym = "OUTRO"
    party.save()
    assert "Ana (PSB–PE)" in render(snapshot)[0]


@pytest.mark.django_db
def test_votes_and_enactments_qualify_without_events():
    from apps.activity.models import Vote

    prop = Proposition.objects.create(
        house="senado",
        external_id=99,
        type_code="PL",
        number_label="PL 99/2020",
        number=99,
        year=2020,
        presented_at=date(2020, 1, 1),
        ementa="Lei",
        enacted_at=date(2026, 10, 1),
    )
    Vote.objects.create(
        proposition=prop,
        held_at=datetime(2026, 9, 30, 12, tzinfo=REPORT_TZ),
        scope="Plenário",
        result="Aprovado",
    )
    snapshot = build_snapshot(START, END)
    assert snapshot[0]["stage"] == "law"
    assert len(snapshot[0]["week_votes"]) == 1
