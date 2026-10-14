from datetime import date
from io import BytesIO
from unittest.mock import Mock

import pytest
from PIL import Image

from apps.legislatures.models import Legislature, Parliamentarian, ParliamentarianTerm, Party
from apps.og import services, storage, tasks
from apps.og.models import ParliamentarianOgImage
from apps.og.renderer import OgData, render
from apps.og.targets import author_slug, build_targets, normalize_photo_url
from apps.propositions.models import (
    AssessmentOrganization,
    Proposition,
    PropositionAnalysis,
    PropositionAnnotation,
    PropositionAuthor,
)

pytestmark = pytest.mark.django_db


def person(name="Tabata Amaral", *, party="PSB", state="SP", photo_url=None, end_date=None):
    parliamentarian = Parliamentarian.objects.create(
        full_name=name.upper(), social_name=name, photo_url=photo_url
    )
    legislature, _ = Legislature.objects.get_or_create(
        number=57, defaults={"start_date": date(2023, 2, 1), "end_date": date(2027, 1, 31)}
    )
    party_obj, _ = Party.objects.get_or_create(acronym=party, defaults={"name": party})
    ParliamentarianTerm.objects.create(
        parliamentarian=parliamentarian,
        legislature_number=legislature,
        party=party_obj,
        house="camara",
        role="Deputado",
        state=state,
        external_id=parliamentarian.pk,
        start_date=date(2023, 2, 1),
        end_date=end_date,
    )
    return parliamentarian


def proposal(number, *authors, presented_at=date(2026, 10, 1), **kwargs):
    proposition = Proposition.objects.create(
        house="camara",
        external_id=number,
        type_code="PL",
        number=number,
        year=2026,
        number_label=f"PL {number}/2026",
        presented_at=presented_at,
        ementa="Proteção das mulheres",
        **{"is_approved": True, **kwargs},
    )
    for author in authors:
        PropositionAuthor.objects.create(proposition=proposition, parliamentarian=author)
    return proposition


def annotate(proposition, is_favorable):
    organization, _ = AssessmentOrganization.objects.get_or_create(name="Avaliadora")
    return PropositionAnnotation.objects.create(
        proposition=proposition,
        organization=organization,
        category="saude",
        is_favorable=is_favorable,
    )


def quiteria(proposition, classification):
    return PropositionAnalysis.objects.create(
        proposition=proposition,
        classification=classification,
        analysis_status=PropositionAnalysis.Status.SUCCEEDED,
    )


@pytest.fixture
def s3(monkeypatch):
    fake = Mock()
    monkeypatch.setattr(storage, "upload", fake.upload)
    monkeypatch.setattr(storage, "delete", fake.delete)
    monkeypatch.setattr(services, "_load_photo", lambda url: None)
    monkeypatch.setattr(services, "render", lambda data: b"png")
    return fake


class TestSiteParity:
    @pytest.mark.parametrize(
        ("name", "slug"),
        [
            ("Tabata Amaral", "tabata-amaral"),
            ("Sâmia Bomfim", "samia-bomfim"),
            ("Maria do Rosário", "maria-do-rosario"),
            ("  Dra. Alessandra Haber  ", "dra-alessandra-haber"),
            ("Professora Goreth / AP", "professora-goreth-ap"),
            ("", None),
            ("---", None),
        ],
    )
    def test_slug_matches_site(self, name, slug):
        assert author_slug(name) == slug

    def test_photo_url_matches_site(self):
        assert normalize_photo_url("http://camara.leg.br/1.jpg") == "https://camara.leg.br/1.jpg"
        assert normalize_photo_url("Indisponível") is None
        assert normalize_photo_url("  ") is None

    def test_counts_follow_public_assessment(self):
        author = person()
        annotate(proposal(1, author), True)
        annotate(proposal(2, author), False)
        quiteria(proposal(3, author), 0)
        # Anotação humana prevalece sobre a QuitérIA.
        prop = proposal(4, author)
        quiteria(prop, 0)
        annotate(prop, False)
        proposal(5, author)  # sem avaliação: não conta
        proposal(6, author, is_approved=False)  # fora do escopo público

        target = build_targets()[author.pk]

        assert (target.favorable, target.unfavorable) == (2, 2)
        assert target.affiliation == "PSB/SP"
        assert target.name == "Tabata Amaral"
        assert target.s3_key == "atividade-legislativa/autoria/tabata-amaral/og.png"

    def test_affiliation_prefers_open_term(self):
        author = person(party="PT", state="RJ", end_date=date(2023, 1, 31))
        legislature = Legislature.objects.get(number=57)
        ParliamentarianTerm.objects.create(
            parliamentarian=author,
            legislature_number=legislature,
            party=Party.objects.create(acronym="PSOL", name="PSOL"),
            house="camara",
            role="Deputado",
            state="SP",
            external_id=999,
            start_date=date(2023, 2, 1),
        )
        proposal(1, author)

        assert build_targets()[author.pk].affiliation == "PSOL/SP"

    def test_first_author_seen_keeps_colliding_slug(self):
        recent = person("Ana Paula")
        older = person("Ana Paula", party="PT")
        proposal(1, older, presented_at=date(2025, 1, 1))
        proposal(2, recent, presented_at=date(2026, 1, 1))

        assert set(build_targets()) == {recent.pk}

    def test_only_authors_in_public_activity_get_images(self):
        author = person()
        person("Sem Autoria")
        proposal(1, author)

        assert set(build_targets()) == {author.pk}


class TestSync:
    def test_unchanged_state_publishes_once(self, s3):
        author = person()
        annotate(proposal(1, author), True)

        assert tasks.render_parliamentarian_og(author.pk) == "rendered"
        assert tasks.render_parliamentarian_og(author.pk) == "unchanged"

        s3.upload.assert_called_once()
        assert s3.upload.call_args.args[0] == "atividade-legislativa/autoria/tabata-amaral/og.png"

    @pytest.mark.parametrize("change", ["counts", "party", "name", "photo"])
    def test_visible_change_renders_again(self, s3, change):
        author = person()
        prop = proposal(1, author)
        tasks.render_parliamentarian_og(author.pk)
        if change == "counts":
            quiteria(prop, 1)
        elif change == "party":
            ParliamentarianTerm.objects.filter(parliamentarian=author).update(
                party=Party.objects.create(acronym="PT", name="PT")
            )
        elif change == "name":
            Parliamentarian.objects.filter(pk=author.pk).update(social_name="Tabata Pontes")
        else:
            Parliamentarian.objects.filter(pk=author.pk).update(photo_url="https://x/1.jpg")

        assert tasks.render_parliamentarian_og(author.pk) == "rendered"
        assert s3.upload.call_count == 2

    def test_invisible_change_does_not_render(self, s3):
        author = person()
        proposal(1, author)
        tasks.render_parliamentarian_og(author.pk)
        Parliamentarian.objects.filter(pk=author.pk).update(bio="Nova biografia")

        assert tasks.render_parliamentarian_og(author.pk) == "unchanged"

    def test_rename_moves_image_to_new_slug(self, s3):
        author = person()
        proposal(1, author)
        tasks.render_parliamentarian_og(author.pk)
        Parliamentarian.objects.filter(pk=author.pk).update(social_name="Tabata Pontes")

        tasks.render_parliamentarian_og(author.pk)

        s3.delete.assert_called_once_with("atividade-legislativa/autoria/tabata-amaral/og.png")
        assert ParliamentarianOgImage.objects.get().s3_key == (
            "atividade-legislativa/autoria/tabata-pontes/og.png"
        )

    def test_author_leaving_public_activity_loses_image(self, s3):
        author = person()
        prop = proposal(1, author)
        tasks.render_parliamentarian_og(author.pk)
        Proposition.objects.filter(pk=prop.pk).update(is_approved=False)

        assert tasks.render_parliamentarian_og(author.pk) == "deleted"
        s3.delete.assert_called_once()
        assert not ParliamentarianOgImage.objects.exists()

    def test_missing_photo_keeps_retrying(self, s3):
        author = person(photo_url="https://x/1.jpg")
        proposal(1, author)

        tasks.render_parliamentarian_og(author.pk)
        record = ParliamentarianOgImage.objects.get()

        assert record.fingerprint == ""
        assert tasks.render_parliamentarian_og(author.pk) == "rendered"

    def test_upload_failure_is_recorded(self, s3):
        author = person()
        proposal(1, author)
        tasks.render_parliamentarian_og(author.pk)
        s3.upload.side_effect = RuntimeError("boom")
        Parliamentarian.objects.filter(pk=author.pk).update(social_name="Outra")

        assert tasks.render_parliamentarian_og(author.pk) == "failed"
        assert ParliamentarianOgImage.objects.get().last_error == "RuntimeError: boom"


class TestEvents:
    def test_events_are_debounced_per_parliamentarian(
        self, settings, monkeypatch, django_capture_on_commit_callbacks
    ):
        settings.OG_S3_BUCKET = "elas-no-congresso-site"
        scheduled = Mock()
        monkeypatch.setattr(tasks.render_parliamentarian_og, "apply_async", scheduled)
        author = person()

        with django_capture_on_commit_callbacks(execute=True):
            for number in range(1, 4):
                quiteria(proposal(number, author), 0)

        scheduled.assert_called_once_with(
            args=[author.pk], countdown=settings.OG_RENDER_DELAY_SECONDS
        )

    def test_without_bucket_schedules_nothing(
        self, settings, monkeypatch, django_capture_on_commit_callbacks
    ):
        settings.OG_S3_BUCKET = ""
        scheduled = Mock()
        monkeypatch.setattr(tasks.render_parliamentarian_og, "apply_async", scheduled)

        with django_capture_on_commit_callbacks(execute=True):
            quiteria(proposal(1, person()), 0)

        scheduled.assert_not_called()


class TestRenderer:
    def test_renders_og_png_with_and_without_photo(self):
        photo = BytesIO()
        Image.new("RGB", (354, 472), (200, 100, 50)).save(photo, "JPEG")
        for portrait in (photo.getvalue(), None):
            png = render(OgData("Tabata Amaral", "PSB/SP", 3, 1, portrait))
            image = Image.open(BytesIO(png))
            assert image.size == (1200, 630)
            assert image.format == "PNG"
