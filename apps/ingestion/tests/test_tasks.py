import contextlib
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.ingestion import tasks
from apps.ingestion.models import IngestionRun
from apps.legislatures.models import Legislature, Parliamentarian, ParliamentarianTerm, Party
from apps.propositions.models import AssessmentOrganization, Proposition, PropositionAnnotation
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

    def fetch_tramitations(self, _id, **kwargs):
        return []

    def fetch_related(self, _id):
        return []

    def fetch_authors(self, _id):
        return self._a

    def fetch_deputy(self, _id):
        return self._dep


class _FakeSenado:
    def __init__(self, summary, detail, movements, texts=None, authors=None):
        self._s, self._d, self._m = summary, detail, movements
        self._s["IdentificacaoMateria"]["IdentificacaoProcesso"] = 99
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

    def fetch_process(self, _id):
        return {"situacaoAtual": "Em tramitação", "tramitando": "Sim", "autuacoes": []}

    def fetch_documents(self, _id):
        return []

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


class _RefreshCamara:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def fetch_detail(self, _external_id):
        return {
            "statusProposicao": {
                "codSituacao": 1140,
                "descricaoSituacao": "Transformado em Norma Jurídica",
                "dataHora": "2026-08-07T12:00:00",
            }
        }

    def fetch_tramitations(self, _external_id):
        return [
            {
                "sequencia": 1,
                "codSituacao": 1140,
                "dataHora": "2026-08-07T12:00:00",
                "descricaoTramitacao": "Transformado na Lei Ordinária 15.421/2026.",
            }
        ]


class _RefreshSenado:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def fetch_process(self, _process_id):
        return {
            "situacaoAtual": "TRANSFORMADA EM NORMA JURÍDICA",
            "tramitando": "Não",
            "autuacoes": [
                {
                    "situacoes": [{"idTipo": 64, "descricao": "TRANSFORMADA EM NORMA JURÍDICA"}],
                    "informesLegislativos": [
                        {
                            "id": 2,
                            "data": "2026-08-08 12:00:00",
                            "idSituacaoIniciada": 64,
                            "descricao": "Transformada na Lei Ordinária nº 15.422, de 2026.",
                        }
                    ],
                }
            ],
        }


def _make_term(*, external_id, house, start_date, end_date, parliamentarian=None, legislature=57):
    parliamentarian = parliamentarian or Parliamentarian.objects.create(
        full_name=f"Pessoa {house} {external_id}"
    )
    legislature_obj, _ = Legislature.objects.get_or_create(
        number=legislature,
        defaults={"start_date": date(2023, 2, 1), "end_date": date(2027, 1, 31)},
    )
    party = Party.objects.create(acronym=f"P{house}{external_id}{legislature}", name="Partido")
    return ParliamentarianTerm.objects.create(
        parliamentarian=parliamentarian,
        legislature_number=legislature_obj,
        party=party,
        house=house,
        role="Parlamentar",
        state="SP",
        external_id=external_id,
        start_date=start_date,
        end_date=end_date,
    )


class _FakeProfileClient:
    def __init__(self, profiles, failures=()):
        self.profiles = profiles
        self.failures = set(failures)
        self.requested = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def fetch_profile(self, external_id):
        self.requested.append(external_id)
        if external_id in self.failures:
            raise RuntimeError(f"profile {external_id} unavailable")
        return self.profiles[external_id]

    def fetch_deputy_fronts(self, _external_id):
        return []

    def fetch_deputy_organs(self, _external_id):
        return []

    def fetch_senator_committees(self, _external_id):
        return []

    def fetch_senator_party_affiliations(self, _external_id):
        return []

    def fetch_senator_leaderships(self, _external_id):
        return []

    def fetch_senator_posts(self, _external_id):
        return []


def _camara_profile(external_id):
    return {
        "id": external_id,
        "uri": f"https://dadosabertos.camara.leg.br/api/v2/deputados/{external_id}",
        "nomeCivil": "Nome Câmara",
        "sexo": "F",
        "ultimoStatus": {"nome": "Nome Público Câmara", "urlFoto": "https://camara/foto.jpg"},
    }


def _senado_profile(external_id):
    return {
        "IdentificacaoParlamentar": {
            "CodigoParlamentar": str(external_id),
            "NomeParlamentar": "Nome Público Senado",
            "NomeCompletoParlamentar": "Nome Completo Senado",
            "SexoParlamentar": "Masculino",
            "UrlFotoParlamentar": "https://senado/foto.jpg",
            "UrlPaginaParlamentar": f"https://senado/perfil/{external_id}",
        },
    }


@pytest.mark.django_db
class TestPersist:
    def test_upsert_creates_with_event_authors_themes(self):
        Party.objects.get_or_create(acronym="MDB", defaults={"name": "MDB"})
        pk = tasks._persist(
            _camara_kwargs(),
            {"event_at": timezone.now(), "situation": "Em pauta"},
            [
                {
                    "name": "Jader Barbalho",
                    "kind": "parlamentar",
                    "party": "MDB",
                    "state": "PA",
                    "order": 1,
                }
            ],
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
        assert (
            tasks._slugify("Direitos Sexuais e Reprodutivos") == "direitos-sexuais-e-reprodutivos"
        )
        assert tasks._slugify("!!!") == "tema"


@pytest.mark.django_db
class TestClassifyProposition:
    def test_missing_proposition_is_noop(self):
        assert tasks.classify_proposition(123456789) is None

    def test_registers_document_for_extraction(self, monkeypatch):
        from apps.propositions.models import PropositionDocument

        pk = tasks._persist(
            {**_camara_kwargs(), "full_text_url": "https://x/doc.pdf"}, None, [], []
        )
        tasks.classify_proposition(pk)
        doc = PropositionDocument.objects.get(proposition_id=pk)
        assert doc.url == "https://x/doc.pdf"
        assert doc.status == "pending"

    def test_without_url_skips_extraction(self):
        pk = tasks._persist(_camara_kwargs(), None, [], [])
        # full_text_url ausente → não chama extração; apenas loga.
        assert tasks.classify_proposition(pk) is None

    @override_settings(QUITERIA_ENABLED=True)
    def test_persists_quiteria_prediction_and_enqueues_matching(
        self, monkeypatch, settings, django_capture_on_commit_callbacks
    ):
        from apps.propositions.models import PropositionAnalysis
        from apps.propositions.quiteria import QuiteriaPrediction

        settings.QUITERIA_ENABLED = False
        pk = tasks._persist(_camara_kwargs(), None, [], [])
        settings.QUITERIA_ENABLED = True
        monkeypatch.setattr(
            "apps.propositions.quiteria.get_classifier",
            lambda: SimpleNamespace(
                classify=lambda input_text: QuiteriaPrediction(
                    input_text="texto de teste",
                    theme_category="saude",
                    theme_confidence=0.9,
                    theme_scores={"LABEL_7": 0.9},
                    favorability_probability=0.3,
                    favorability_scores={"LABEL_0": 0.7, "LABEL_1": 0.3},
                    favorability_label=1,
                )
            ),
        )

        with django_capture_on_commit_callbacks(execute=True):
            tasks.classify_proposition(pk)

        analysis = PropositionAnalysis.objects.get(proposition_id=pk)
        assert analysis.analysis_status == PropositionAnalysis.Status.SUCCEEDED
        assert analysis.theme_category == "saude"
        assert float(analysis.theme_confidence) == 0.9
        assert analysis.classification == 1
        assert float(analysis.classification_probability) == 0.3


@pytest.mark.django_db
class TestIngestCamaraFlow:
    def test_full_flow(self, monkeypatch, camara_payload):
        # autor deputado real (com sexo/partido) para exercitar fetch_deputy/enrich
        authors = [
            {
                "nome": "Deputada X",
                "tipo": "Deputado(a)",
                "uri": "https://dadosabertos.camara.leg.br/api/v2/deputados/204554",
            }
        ]
        sigla = camara_payload["deputy"]["ultimoStatus"]["siglaPartido"]
        Party.objects.get_or_create(acronym=sigla, defaults={"name": sigla})
        monkeypatch.setattr("apps.ingestion.fulltext.extract_pdf_text", lambda url: None)
        monkeypatch.setattr(
            tasks,
            "CamaraClient",
            lambda: _FakeCamara(
                camara_payload["summary"],
                camara_payload["detail"],
                authors,
                camara_payload["deputy"],
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
        assert run.status == IngestionRun.Status.FAILED
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
        assert IngestionRun.objects.filter(
            house="camara", status=IngestionRun.Status.FAILED
        ).exists()


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
        assert run.status == IngestionRun.Status.FAILED
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
        assert IngestionRun.objects.filter(
            house="senado", status=IngestionRun.Status.FAILED
        ).exists()


@pytest.mark.django_db
class TestEnrichParliamentarianProfiles:
    def test_enriches_current_unique_terms_and_keeps_source_identity(self, monkeypatch):
        today = timezone.localdate()
        parliamentarian = Parliamentarian.objects.create(full_name="Pessoa Câmara")
        _make_term(
            external_id=101,
            house="camara",
            start_date=today - timedelta(days=10),
            end_date=today,
            parliamentarian=parliamentarian,
            legislature=57,
        )
        _make_term(
            external_id=101,
            house="camara",
            start_date=today - timedelta(days=20),
            end_date=today + timedelta(days=10),
            parliamentarian=parliamentarian,
            legislature=56,
        )
        _make_term(
            external_id=202,
            house="senado",
            start_date=today - timedelta(days=10),
            end_date=None,
            legislature=57,
        )
        _make_term(
            external_id=303,
            house="camara",
            start_date=today - timedelta(days=20),
            end_date=today - timedelta(days=1),
            legislature=56,
        )
        _make_term(
            external_id=404,
            house="senado",
            start_date=today + timedelta(days=1),
            end_date=None,
            legislature=57,
        )

        camara = _FakeProfileClient({101: _camara_profile(101)})
        senado = _FakeProfileClient({202: _senado_profile(202)})
        calls = []
        monkeypatch.setattr(tasks, "CamaraClient", lambda: camara)
        monkeypatch.setattr(tasks, "SenadoClient", lambda: senado)
        monkeypatch.setattr(tasks, "_load_tse_index", lambda: ({}, 0))
        monkeypatch.setattr(
            tasks,
            "_load_senado_front_snapshot",
            lambda: SimpleNamespace(fronts=(), failed_fronts=0),
        )
        monkeypatch.setattr(tasks, "upsert_source_profile", lambda **kwargs: calls.append(kwargs))

        result = tasks.enrich_parliamentarian_profiles()

        assert result == {
            "skipped": False,
            "processed": 2,
            "failed": 0,
            "camara": {"processed": 1, "failed": 0},
            "senado": {"processed": 1, "failed": 0},
            "senado_fronts": {"processed": 0, "failed": 0, "memberships": 0},
            "tse": {"processed": 0, "unresolved": 2, "ambiguous": 0, "failed": 0},
            "terms": {
                "members": 0,
                "created": 0,
                "updated": 0,
                "failed": 0,
                "camara": {"members": 0, "created": 0, "updated": 0, "failed": 0},
                "senado": {"members": 0, "created": 0, "updated": 0, "failed": 0},
            },
        }
        assert camara.requested == [101]
        assert senado.requested == [202]
        assert calls == [
            {
                "source": "camara",
                "source_key": 101,
                "house": "camara",
                "profile_values": {
                    "external_id": 101,
                    "full_name": "Nome Câmara",
                    "social_name": "Nome Público Câmara",
                    "gender": "F",
                    "photo_url": "https://camara/foto.jpg",
                    "birthplace": None,
                },
                "source_url": "https://dadosabertos.camara.leg.br/api/v2/deputados/101",
            },
            {
                "source": "senado",
                "source_key": 202,
                "house": "senado",
                "profile_values": {
                    "external_id": 202,
                    "full_name": "Nome Completo Senado",
                    "social_name": "Nome Público Senado",
                    "gender": "M",
                    "photo_url": "https://senado/foto.jpg",
                    "birthplace": None,
                },
                "source_url": "https://senado/perfil/202",
            },
        ]

    def test_failure_isolated_per_term(self, monkeypatch):
        today = timezone.localdate()
        _make_term(
            external_id=301,
            house="camara",
            start_date=today - timedelta(days=1),
            end_date=None,
            legislature=57,
        )
        _make_term(
            external_id=302,
            house="camara",
            start_date=today - timedelta(days=1),
            end_date=None,
            legislature=57,
        )
        _make_term(
            external_id=401,
            house="senado",
            start_date=today - timedelta(days=1),
            end_date=None,
            legislature=57,
        )
        camara = _FakeProfileClient({302: _camara_profile(302)}, failures={301})
        senado = _FakeProfileClient({401: _senado_profile(401)})
        calls = []
        monkeypatch.setattr(tasks, "CamaraClient", lambda: camara)
        monkeypatch.setattr(tasks, "SenadoClient", lambda: senado)
        monkeypatch.setattr(tasks, "_load_tse_index", lambda: ({}, 0))
        monkeypatch.setattr(
            tasks,
            "_load_senado_front_snapshot",
            lambda: SimpleNamespace(fronts=(), failed_fronts=0),
        )
        monkeypatch.setattr(tasks, "upsert_source_profile", lambda **kwargs: calls.append(kwargs))

        result = tasks.enrich_parliamentarian_profiles()

        assert result["processed"] == 2
        assert result["failed"] == 1
        assert result["camara"] == {"processed": 1, "failed": 1}
        assert result["senado"] == {"processed": 1, "failed": 0}
        assert camara.requested == [301, 302]
        assert senado.requested == [401]
        assert {call["source_key"] for call in calls} == {302, 401}

    def test_lock_collision_returns_explicit_skipped_result(self, monkeypatch):
        monkeypatch.setattr(tasks.cache, "add", lambda *args, **kwargs: False)
        clients_called = []
        monkeypatch.setattr(tasks, "CamaraClient", lambda: clients_called.append("camara"))
        monkeypatch.setattr(tasks, "SenadoClient", lambda: clients_called.append("senado"))

        result = tasks.enrich_parliamentarian_profiles()

        assert result == {
            "skipped": True,
            "reason": "lock_held",
            "processed": 0,
            "failed": 0,
            "camara": {"processed": 0, "failed": 0},
            "senado": {"processed": 0, "failed": 0},
            "senado_fronts": {"processed": 0, "failed": 0, "memberships": 0},
            "tse": {"processed": 0, "unresolved": 0, "ambiguous": 0, "failed": 0},
            "terms": {
                "members": 0,
                "created": 0,
                "updated": 0,
                "failed": 0,
                "camara": {"members": 0, "created": 0, "updated": 0, "failed": 0},
                "senado": {"members": 0, "created": 0, "updated": 0, "failed": 0},
            },
        }
        assert clients_called == []


def test_profile_enrichment_is_scheduled_at_03_brt():
    from config.settings import base

    schedule = base.CELERY_BEAT_SCHEDULE["enrich-parliamentarian-profiles-daily"]
    assert schedule["task"] == "apps.ingestion.tasks.enrich_parliamentarian_profiles"
    assert schedule["schedule"].hour == {3}
    assert schedule["schedule"].minute == {0}
    assert base.CELERY_TIMEZONE == "America/Sao_Paulo"


@pytest.mark.django_db
def test_refresh_enacted_propositions_updates_camara_and_closed_senado(monkeypatch):
    organization = AssessmentOrganization.objects.create(name="AzMina")
    camara = Proposition.objects.create(**_camara_kwargs())
    senado = Proposition.objects.create(
        house="senado",
        external_id=777002,
        type_code="PLS",
        number_label="PLS 2/2024",
        number=2,
        year=2024,
        presented_at="2024-01-01",
        ementa="Sobre violência contra a mulher",
        raw_payload={"_senado_process_id": 99},
    )
    for proposition in (camara, senado):
        PropositionAnnotation.objects.create(
            proposition=proposition,
            organization=organization,
            is_favorable=True,
            category="saude",
        )

    monkeypatch.setattr(tasks, "CamaraClient", _RefreshCamara)
    monkeypatch.setattr(tasks, "SenadoClient", _RefreshSenado)
    result = tasks.refresh_enacted_propositions([camara, senado])

    camara.refresh_from_db()
    senado.refresh_from_db()
    assert result == {"processed": 2, "enacted": 2, "events": 2, "failed": 0}
    assert (camara.current_status_code, camara.enacted_law_number) == (1140, 15421)
    assert (senado.current_status_code, senado.enacted_law_number) == (64, 15422)
    assert senado.is_active is False


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
