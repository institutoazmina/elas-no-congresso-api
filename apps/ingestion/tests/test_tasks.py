import contextlib

import pytest
from django.utils import timezone

from apps.ingestion import tasks
from apps.ingestion.models import IngestionRun
from apps.legislatures.models import Party
from apps.propositions.models import Proposition
from apps.taxonomy.models import PropositionTheme

# ── fake clients ──────────────────────────────────────────────────────────────

class _FakeCamara:
    def __init__(self, summary, detail, authors, deputy=None):
        self._s, self._d, self._a = summary, detail, authors
        self._dep = deputy or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def list_propositions(self, start, end):
        yield self._s

    def fetch_detail(self, _id):
        return self._d

    def fetch_authors(self, _id):
        return self._a

    def fetch_deputy(self, _id):
        return self._dep


class _FakeSenado:
    def __init__(self, summary, detail, movements, texts=None, authors=None):
        self._s, self._d, self._m = summary, detail, movements
        self._t = texts or []
        self._a = authors or []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def list_materias(self, day):
        yield self._s

    def fetch_detail(self, _id):
        return self._d

    def fetch_movements(self, _id):
        return self._m

    def fetch_texts(self, _id):
        return self._t

    def fetch_authors(self, _id):
        return self._a


# ── helpers ───────────────────────────────────────────────────────────────────

def _camara_kwargs():
    return {
        "house": "camara",
        "external_id": 777001,
        "type_code": "PL",
        "number_label": "PL 1/2024",
        "number": 1,
        "year": 2024,
        "presented_at": "2024-01-01",
        "ementa": "Sobre violência contra a mulher",
    }


@pytest.mark.django_db
class TestPersist:
    def test_upsert_creates_with_event_authors_themes(self):
        Party.objects.get_or_create(acronym="MDB", defaults={"name": "MDB"})
        pk = tasks._persist(
            _camara_kwargs(),
            {"event_at": timezone.now(), "situation": "Em pauta"},
            [{"name": "Jader Barbalho", "kind": "parlamentar", "party": "MDB", "state": "PA", "order": 1}],
            ["violência contra a mulher"],
        )
        prop = Proposition.objects.get(pk=pk)
        assert prop.events.count() == 1
        author = prop.authors.first()
        assert author.parliamentarian.full_name == "Jader Barbalho"
        assert author.party.acronym == "MDB"
        assert author.state_at_authorship == "PA"
        assert PropositionTheme.objects.filter(proposition=prop).count() == 1

    def test_idempotent_upsert(self):
        pk1 = tasks._persist(_camara_kwargs(), None, [], [])
        pk2 = tasks._persist(_camara_kwargs(), None, [], [])
        assert pk1 == pk2
        assert Proposition.objects.filter(house="camara", external_id=777001).count() == 1

    def test_author_without_resolution_skipped(self):
        pk = tasks._persist(_camara_kwargs(), None, [{"name": "", "order": 1}], [])
        assert Proposition.objects.get(pk=pk).authors.count() == 0

    def test_slugify(self):
        assert tasks._slugify("Direitos Sexuais e Reprodutivos") == "direitos-sexuais-e-reprodutivos"
        assert tasks._slugify("!!!") == "tema"


@pytest.mark.django_db
class TestClassifyProposition:
    def test_missing_proposition_is_noop(self):
        assert tasks.classify_proposition(123456789) is None

    def test_fetches_full_text(self, monkeypatch):
        pk = tasks._persist({**_camara_kwargs(), "full_text_url": "https://x/doc.pdf"}, None, [], [])
        captured = {}
        monkeypatch.setattr(
            "apps.ingestion.fulltext.extract_pdf_text",
            lambda url: captured.setdefault("url", url) or "texto extraido",
        )
        tasks.classify_proposition(pk)
        assert captured["url"] == "https://x/doc.pdf"

    def test_without_url_skips_extraction(self):
        pk = tasks._persist(_camara_kwargs(), None, [], [])
        # full_text_url ausente → não chama extração; apenas loga.
        assert tasks.classify_proposition(pk) is None


@pytest.mark.django_db
class TestIngestCamaraFlow:
    def test_full_flow(self, monkeypatch, camara_payload):
        # autor deputado real (com sexo/partido) para exercitar fetch_deputy/enrich
        authors = [
            {"nome": "Deputada X", "tipo": "Deputado(a)",
             "uri": "https://dadosabertos.camara.leg.br/api/v2/deputados/204554"}
        ]
        sigla = camara_payload["deputy"]["ultimoStatus"]["siglaPartido"]
        Party.objects.get_or_create(acronym=sigla, defaults={"name": sigla})
        monkeypatch.setattr("apps.ingestion.fulltext.extract_pdf_text", lambda url: None)
        monkeypatch.setattr(
            tasks,
            "CamaraClient",
            lambda: _FakeCamara(
                camara_payload["summary"], camara_payload["detail"], authors, camara_payload["deputy"]
            ),
        )
        run_pk = tasks.ingest_camara()
        run = IngestionRun.objects.get(pk=run_pk)
        assert run.status == IngestionRun.Status.SUCCESS
        assert run.upserted_count >= 1
        prop = Proposition.objects.filter(house="camara").first()
        author = prop.authors.first()
        assert author.party is not None  # partido do deputado
        assert author.parliamentarian.gender  # sexo preenchido

    def test_per_item_error_is_counted(self, monkeypatch, camara_payload):
        class _BoomCamara(_FakeCamara):
            def fetch_detail(self, _id):
                raise RuntimeError("api down")

        monkeypatch.setattr(
            tasks,
            "CamaraClient",
            lambda: _BoomCamara(camara_payload["summary"], {}, []),
        )
        run = IngestionRun.objects.get(pk=tasks.ingest_camara())
        assert run.status == IngestionRun.Status.SUCCESS
        assert run.error_count >= 1
        assert run.upserted_count == 0

    def test_irrelevant_is_skipped(self, monkeypatch):
        summary = {"id": 1, "ementa": "Pavimentação de rodovia federal"}
        monkeypatch.setattr(tasks, "CamaraClient", lambda: _FakeCamara(summary, {}, []))
        run = IngestionRun.objects.get(pk=tasks.ingest_camara())
        assert run.relevant_count == 0
        assert run.upserted_count == 0

    def test_outer_failure_marks_run_failed(self, monkeypatch):
        class _Dead:
            def __enter__(self):
                raise RuntimeError("connection refused")

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(tasks, "CamaraClient", lambda: _Dead())
        # eager + retry: a task marca o run como FAILED antes de relançar.
        with contextlib.suppress(Exception):
            tasks.ingest_camara()
        assert IngestionRun.objects.filter(house="camara", status=IngestionRun.Status.FAILED).exists()


@pytest.mark.django_db
class TestIngestSenadoFlow:
    def test_full_flow(self, monkeypatch, senado_payload):
        summary = {
            "IdentificacaoMateria": {
                "CodigoMateria": "167294",
                "SiglaSubtipoMateria": "PL",
                "NumeroMateria": "592",
                "AnoMateria": "2025",
            },
            "Ementa": "Projeto sobre direitos da mulher e maternidade",
            "Autor": "Senador Jader Barbalho (MDB/PA)",
            "DataApresentacao": "2025-02-20",
        }
        monkeypatch.setattr("apps.ingestion.fulltext.extract_pdf_text", lambda url: None)
        autoria = senado_payload["autoria"]["AutoriaMateria"]["Materia"]["Autoria"]["Autor"]
        autoria = autoria if isinstance(autoria, list) else [autoria]
        monkeypatch.setattr(
            tasks,
            "SenadoClient",
            lambda: _FakeSenado(
                summary,
                senado_payload["detail"],
                senado_payload["movements"],
                senado_payload["texts"],
                autoria,
            ),
        )
        run = IngestionRun.objects.get(pk=tasks.ingest_senado())
        assert run.status == IngestionRun.Status.SUCCESS
        assert run.upserted_count >= 1
        prop = Proposition.objects.filter(house="senado").first()
        assert prop is not None
        assert prop.full_text_url and "sdleg-getter" in prop.full_text_url
        author = prop.authors.first()
        assert author.parliamentarian.gender  # sexo via autoria

    def test_irrelevant_is_skipped(self, monkeypatch):
        summary = {"IdentificacaoMateria": {"CodigoMateria": "1"}, "Ementa": "Reforma tributária"}
        monkeypatch.setattr(tasks, "SenadoClient", lambda: _FakeSenado(summary, {}, {}))
        run = IngestionRun.objects.get(pk=tasks.ingest_senado())
        assert run.relevant_count == 0
        assert run.upserted_count == 0

    def test_per_item_error_is_counted(self, monkeypatch):
        summary = {
            "IdentificacaoMateria": {"CodigoMateria": "2"},
            "Ementa": "Direitos da mulher e maternidade",
        }

        class _BoomSenado(_FakeSenado):
            def fetch_detail(self, _id):
                raise RuntimeError("senado api down")

        monkeypatch.setattr(tasks, "SenadoClient", lambda: _BoomSenado(summary, {}, {}))
        run = IngestionRun.objects.get(pk=tasks.ingest_senado())
        assert run.status == IngestionRun.Status.SUCCESS
        assert run.error_count >= 1
        assert run.upserted_count == 0

    def test_outer_failure_marks_run_failed(self, monkeypatch):
        class _Dead:
            def __enter__(self):
                raise RuntimeError("senado down")

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(tasks, "SenadoClient", lambda: _Dead())
        with contextlib.suppress(Exception):
            tasks.ingest_senado()
        assert IngestionRun.objects.filter(house="senado", status=IngestionRun.Status.FAILED).exists()


@pytest.mark.django_db
class TestModelsAndAdmin:
    def test_ingestion_run_str(self):
        run = IngestionRun.objects.create(
            house="camara", window_start="2024-01-01", window_end="2024-01-02"
        )
        assert "camara" in str(run)

    def test_admin_no_add(self):
        from django.contrib.admin.sites import site

        from apps.ingestion.models import IngestionRun as M

        assert site._registry[M].has_add_permission(None) is False
