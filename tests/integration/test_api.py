import io
import json
from datetime import datetime

import pytest
from django.test import Client

from apps.legislatures.models import Legislature, Parliamentarian, ParliamentarianTerm, Party
from apps.propositions.dataset import FIELDS
from apps.propositions.models import (
    AssessmentOrganization,
    Proposition,
    PropositionAnalysis,
    PropositionAnnotation,
    PropositionAuthor,
)
from apps.taxonomy.models import Theme


@pytest.mark.django_db
class TestPropositionsEndpoints:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = Client()
        leg, _ = Legislature.objects.update_or_create(  # já vem do seed (legislatures.0002)
            number=57,
            defaults={"start_date": "2023-02-01", "end_date": "2027-01-31"},
        )
        party = Party.objects.create(acronym="PT", name="Partido dos Trabalhadores")
        self.parliamentarian = Parliamentarian.objects.create(
            full_name="Maria Silva", gender="F"
        )
        self.term = ParliamentarianTerm.objects.create(
            parliamentarian=self.parliamentarian,
            legislature_number=leg,
            party=party,
            house="camara",
            role="Titular",
            state="SP",
            external_id=1,
            start_date="2023-02-01",
        )
        self.proposition = Proposition.objects.create(
            external_id=1,
            house="camara",
            type_code="pl",
            is_approved=True,
            number_label="PL 123/2024",
            number=123,
            year=2024,
            presented_at="2024-01-01",
            ementa="Test proposition about women rights",
            current_status="Em tramitação",
        )

    def test_list_propositions(self):
        response = self.client.get("/api/v1/propositions/")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data

    def test_busca_por_texto_encontra_pela_ementa_e_pelo_numero(self):
        alvo = self.proposition.number_label

        por_ementa = self.client.get("/api/v1/propositions/?q=women")
        por_numero_simples = self.client.get("/api/v1/propositions/?q=123")
        por_numero = self.client.get("/api/v1/propositions/", {"q": "PL 123/2024"})
        sem_relacao = self.client.get("/api/v1/propositions/?q=zzz-nao-existe")

        assert por_ementa.status_code == 200
        assert [p["number_label"] for p in por_ementa.json()["items"]] == [alvo]
        assert [p["number_label"] for p in por_numero_simples.json()["items"]] == [alvo]
        assert [p["number_label"] for p in por_numero.json()["items"]] == [alvo]
        assert sem_relacao.json()["items"] == []

    def test_busca_por_nome_completo_e_social_do_autor(self):
        author = Parliamentarian.objects.create(
            full_name="Érika Santos Hilton",
            social_name="Erika Hilton",
        )
        PropositionAuthor.objects.create(
            proposition=self.proposition,
            parliamentarian=author,
            order_index=1,
        )

        por_nome_completo = self.client.get("/api/v1/propositions/", {"q": "santos hil"})
        por_nome_social = self.client.get("/api/v1/propositions/", {"q": "ERIKA HILTON"})
        sem_acento = self.client.get("/api/v1/propositions/", {"q": "erika santos"})

        assert [p["id"] for p in por_nome_completo.json()["items"]] == [self.proposition.pk]
        assert [p["id"] for p in por_nome_social.json()["items"]] == [self.proposition.pk]
        assert [p["id"] for p in sem_acento.json()["items"]] == [self.proposition.pk]

    def test_busca_por_parlamentar_inclui_coautoria(self):
        coauthor = Parliamentarian.objects.create(full_name="João da Silva")
        PropositionAuthor.objects.create(
            proposition=self.proposition,
            parliamentarian=coauthor,
            order_index=2,
        )

        response = self.client.get("/api/v1/propositions/", {"q": "joao da sil"})

        assert response.status_code == 200
        assert [p["id"] for p in response.json()["items"]] == [self.proposition.pk]

    def test_busca_por_autor_pagina_proposicoes_distintas_na_ordem_atual(self):
        erika = Parliamentarian.objects.create(full_name="Érika Hilton")
        erika_coauthor = Parliamentarian.objects.create(full_name="Erika Souza")
        newest = Proposition.objects.create(
            external_id=2,
            house="camara",
            type_code="pl",
            is_approved=True,
            number_label="PL 124/2024",
            number=124,
            year=2024,
            presented_at="2024-02-01",
            ementa="Another proposition",
        )
        PropositionAuthor.objects.create(
            proposition=self.proposition,
            parliamentarian=erika,
            order_index=1,
        )
        PropositionAuthor.objects.create(
            proposition=self.proposition,
            parliamentarian=erika_coauthor,
            order_index=2,
        )
        PropositionAuthor.objects.create(
            proposition=newest,
            parliamentarian=erika,
            order_index=2,
        )

        first_page = self.client.get(
            "/api/v1/propositions/",
            {"q": "erika", "limit": 1, "offset": 0},
        ).json()
        second_page = self.client.get(
            "/api/v1/propositions/",
            {"q": "erika", "limit": 1, "offset": 1},
        ).json()

        assert first_page["count"] == 2
        assert second_page["count"] == 2
        assert [p["id"] for p in first_page["items"]] == [newest.pk]
        assert [p["id"] for p in second_page["items"]] == [self.proposition.pk]

    def test_busca_por_autor_preserva_os_demais_filtros(self):
        author = Parliamentarian.objects.create(full_name="Érika Hilton")
        PropositionAuthor.objects.create(
            proposition=self.proposition,
            parliamentarian=author,
        )

        matching = self.client.get(
            "/api/v1/propositions/",
            {"q": "erika", "house": "camara", "year": 2024, "active": "true"},
        ).json()
        excluded = self.client.get(
            "/api/v1/propositions/",
            {"q": "erika", "house": "senado"},
        ).json()

        assert matching["count"] == 1
        assert [p["id"] for p in matching["items"]] == [self.proposition.pk]
        assert excluded == {"items": [], "count": 0}

    def test_openapi_descreve_todos_os_campos_pesquisados_por_q(self):
        schema = self.client.get("/api/v1/openapi.json").json()
        parameters = schema["paths"]["/api/v1/propositions/"]["get"]["parameters"]
        q_parameter = next(parameter for parameter in parameters if parameter["name"] == "q")

        assert "ementa" in q_parameter["description"]
        assert "número" in q_parameter["description"]
        assert "nome completo ou social" in q_parameter["description"]

    def test_ordenacao_por_data_nas_duas_direcoes_e_desempate_por_id(self):
        same_date = Proposition.objects.create(
            external_id=2,
            house="camara",
            type_code="pl",
            is_approved=True,
            number_label="PL 124/2024",
            number=124,
            year=2024,
            presented_at="2024-01-01",
            ementa="Same-date proposition",
        )
        newest = Proposition.objects.create(
            external_id=3,
            house="camara",
            type_code="pl",
            is_approved=True,
            number_label="PL 125/2024",
            number=125,
            year=2024,
            presented_at="2024-02-01",
            ementa="Newest proposition",
        )

        default = self.client.get("/api/v1/propositions/").json()
        descending = self.client.get("/api/v1/propositions/", {"sort": "newest"}).json()
        ascending = self.client.get("/api/v1/propositions/", {"sort": "oldest"}).json()

        expected_newest = [newest.pk, same_date.pk, self.proposition.pk]
        assert [item["id"] for item in default["items"]] == expected_newest
        assert [item["id"] for item in descending["items"]] == expected_newest
        assert [item["id"] for item in ascending["items"]] == [
            self.proposition.pk,
            same_date.pk,
            newest.pk,
        ]

    def test_ordenacao_acontece_antes_da_paginacao(self):
        middle = Proposition.objects.create(
            external_id=2,
            house="camara",
            type_code="pl",
            is_approved=True,
            number_label="PL 124/2024",
            number=124,
            year=2024,
            presented_at="2024-02-01",
            ementa="Middle proposition",
        )
        Proposition.objects.create(
            external_id=3,
            house="camara",
            type_code="pl",
            is_approved=True,
            number_label="PL 125/2024",
            number=125,
            year=2024,
            presented_at="2024-03-01",
            ementa="Newest proposition",
        )

        page = self.client.get(
            "/api/v1/propositions/",
            {"sort": "oldest", "limit": 1, "offset": 1},
        ).json()

        assert page["count"] == 3
        assert [item["id"] for item in page["items"]] == [middle.pk]

    def test_ordenacao_funciona_com_busca_por_autor(self):
        author = Parliamentarian.objects.create(full_name="Érika Hilton")
        oldest = Proposition.objects.create(
            external_id=2,
            house="camara",
            type_code="pl",
            is_approved=True,
            number_label="PL 122/2023",
            number=122,
            year=2023,
            presented_at="2023-12-01",
            ementa="Older authored proposition",
        )
        PropositionAuthor.objects.create(
            proposition=self.proposition,
            parliamentarian=author,
        )
        PropositionAuthor.objects.create(
            proposition=oldest,
            parliamentarian=author,
        )

        response = self.client.get(
            "/api/v1/propositions/",
            {"q": "erika", "sort": "oldest"},
        )

        assert response.status_code == 200
        assert [item["id"] for item in response.json()["items"]] == [
            oldest.pk,
            self.proposition.pk,
        ]

    def test_ordenacao_invalida_retorna_422(self):
        response = self.client.get("/api/v1/propositions/", {"sort": "recent"})

        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["query", "sort"]

    def test_openapi_documenta_valores_e_padrao_da_ordenacao(self):
        schema = self.client.get("/api/v1/openapi.json").json()
        parameters = schema["paths"]["/api/v1/propositions/"]["get"]["parameters"]
        sort_parameter = next(parameter for parameter in parameters if parameter["name"] == "sort")

        assert sort_parameter["schema"]["enum"] == ["newest", "oldest"]
        assert sort_parameter["schema"]["default"] == "newest"
        assert "presented_at" in sort_parameter["description"]

    def test_list_propositions_pagination(self):
        response = self.client.get("/api/v1/propositions/?limit=10&offset=0")
        assert response.status_code == 200

    def test_get_proposition_detail(self):
        response = self.client.get(f"/api/v1/propositions/{self.proposition.pk}")
        assert response.status_code == 200
        data = response.json()
        assert data["number"] == 123

    def test_get_proposition_not_found(self):
        response = self.client.get("/api/v1/propositions/99999")
        assert response.status_code == 404


@pytest.mark.django_db
class TestDatasetEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = Client()
        party = Party.objects.create(acronym="PT", name="Partido dos Trabalhadores")
        maria = Parliamentarian.objects.create(full_name="Maria Silva", gender="F")
        joao = Parliamentarian.objects.create(full_name="João Souza", gender="M")
        self.prop = Proposition.objects.create(
            external_id=42, house="camara", type_code="pl",
            number_label="PL 123/2024", number=123, year=2024,
            presented_at="2024-01-01", ementa="Sobre direitos das mulheres",
            full_text="texto integral", tramitation_url="https://camara.leg.br/42",
        )
        # 2 autores → cada anotação vira 2 linhas
        PropositionAuthor.objects.create(
            proposition=self.prop, parliamentarian=maria, party=party,
            state_at_authorship="SP", order_index=1,
        )
        PropositionAuthor.objects.create(
            proposition=self.prop, parliamentarian=joao, party=party,
            state_at_authorship="RJ", order_index=2,
        )
        # 2 anotações (favorável / desfavorável)
        anis = AssessmentOrganization.objects.create(name="Anis")
        themis = AssessmentOrganization.objects.create(name="Themis")
        PropositionAnnotation.objects.create(
            proposition=self.prop, organization=anis, is_favorable=True,
            relevance="muito_relevante", category="direitos_sexuais_reprodutivos",
            legacy_theme="Aborto", comments="Observação da Anis",
        )
        PropositionAnnotation.objects.create(
            proposition=self.prop, organization=themis, is_favorable=False,
            relevance="pouco_relevante", category="saude", legacy_theme="Saúde",
        )

    def test_row_per_annotation_times_author(self):
        r = self.client.get("/api/v1/dataset/")
        assert r.status_code == 200
        data = r.json()
        # 2 anotações × 2 autores = 4 linhas
        assert data["count"] == 4
        assert len(data["items"]) == 4

    def test_field_mapping_and_labels(self):
        r = self.client.get("/api/v1/dataset/")
        rows = r.json()["items"]
        assert set(rows[0]) == {
            "house", "id", "uri", "type_code", "name", "year", "summary",
            "full_text", "author", "author_index", "party", "state", "gender",
            "assessment", "relevance", "theme", "is_favorable", "legacy_theme",
            "comments",
        }
        # id = external_id
        assert all(row["id"] == 42 for row in rows)
        assert all(row["uri"] == "https://camara.leg.br/42" for row in rows)
        # rótulos em português
        assert {row["assessment"] for row in rows} == {"Favorável", "Desfavorável"}
        assert {row["gender"] for row in rows} == {"Feminino", "Masculino"}
        assert {row["relevance"] for row in rows} == {"Muito relevante", "Pouco relevante"}
        # `theme` é a categoria (taxonomia fechada); o texto livre foi para `legacy_theme`
        assert {row["theme"] for row in rows} == {"Direitos Sexuais e Reprodutivos", "Saúde"}
        assert {row["legacy_theme"] for row in rows} == {"Aborto", "Saúde"}
        assert {row["comments"] for row in rows} == {"Observação da Anis", None}
        # autor / party / state por autor
        assert {row["author"] for row in rows} == {"Maria Silva", "João Souza"}
        assert {row["state"] for row in rows} == {"SP", "RJ"}
        assert all(row["party"] == "PT" for row in rows)
        # author_index = proposition_authors.order_index, e as linhas de cada
        # anotação saem ordenadas por ele
        assert {(row["author"], row["author_index"]) for row in rows} == {
            ("Maria Silva", 1), ("João Souza", 2),
        }
        assert [row["author_index"] for row in rows] == [1, 2, 1, 2]

    def test_is_favorable_matches_assessment(self):
        rows = self.client.get("/api/v1/dataset/").json()["items"]
        for row in rows:
            assert row["is_favorable"] is (row["assessment"] == "Favorável")

    def test_default_returns_only_labeled(self):
        # anotação sem rótulo (is_favorable=None) → excluída por padrão
        PropositionAnnotation.objects.create(
            proposition=self.prop,
            organization=AssessmentOrganization.objects.create(name="Cfemea"),
            is_favorable=None, category="violencias_de_genero",
        )
        default = self.client.get("/api/v1/dataset/").json()["count"]
        allrows = self.client.get(
            "/api/v1/dataset/", {"include_unlabeled": "true"}
        ).json()["count"]
        assert default == 4  # só as 2 rotuladas × 2 autores
        assert allrows == 6  # 3 anotações × 2 autores

    def test_pagination_and_house_filter(self):
        r = self.client.get("/api/v1/dataset/", {"limit": 2, "offset": 0})
        assert len(r.json()["items"]) == 2
        assert r.json()["count"] == 4
        assert self.client.get("/api/v1/dataset/", {"house": "senado"}).json()["count"] == 0

    def test_download_csv(self):
        r = self.client.get("/api/v1/dataset/download", {"format": "csv"})
        assert r.status_code == 200
        assert r["Content-Type"].startswith("text/csv")
        assert "attachment" in r["Content-Disposition"] and "dataset.csv" in r["Content-Disposition"]
        body = b"".join(r.streaming_content).decode()
        lines = [ln for ln in body.splitlines() if ln]
        header = lines[0].split(",")
        # `legacy_theme`/`comments` entraram no FIM: as colunas anteriores não se deslocam
        assert header == [
            "house", "id", "uri", "type_code", "name", "year", "summary",
            "full_text", "author", "author_index", "party", "state", "gender",
            "assessment", "relevance", "theme", "is_favorable", "legacy_theme",
            "comments",
        ]
        assert len(lines) - 1 == 4  # header + 4 linhas (2 anotações × 2 autores)

    def test_download_jsonl(self):
        r = self.client.get("/api/v1/dataset/download", {"format": "jsonl"})
        assert r.status_code == 200
        assert r["Content-Type"] == "application/x-ndjson"
        rows = [json.loads(ln) for ln in b"".join(r.streaming_content).decode().splitlines() if ln]
        assert len(rows) == 4
        assert set(rows[0]) == set(FIELDS)
        assert {row["author"] for row in rows} == {"Maria Silva", "João Souza"}

    def test_download_parquet(self):
        import pyarrow.parquet as pq

        r = self.client.get("/api/v1/dataset/download", {"format": "parquet"})
        assert r.status_code == 200
        assert r["Content-Type"] == "application/vnd.apache.parquet"
        table = pq.read_table(io.BytesIO(r.content))
        assert table.num_rows == 4
        assert table.column_names == FIELDS

    def test_download_invalid_format(self):
        r = self.client.get("/api/v1/dataset/download", {"format": "xml"})
        assert r.status_code == 400

    def test_download_respects_only_labeled_default(self):
        PropositionAnnotation.objects.create(
            proposition=self.prop,
            organization=AssessmentOrganization.objects.create(name="Cfemea"),
            is_favorable=None, category="violencias_de_genero",
        )
        r = self.client.get("/api/v1/dataset/download", {"format": "jsonl"})
        rows = [ln for ln in b"".join(r.streaming_content).decode().splitlines() if ln]
        assert len(rows) == 4  # só as rotuladas (2 × 2 autores); a sem rótulo fica de fora


@pytest.mark.django_db
class TestParliamentariansEndpoints:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = Client()
        leg, _ = Legislature.objects.update_or_create(  # já vem do seed (legislatures.0002)
            number=57,
            defaults={"start_date": "2023-02-01", "end_date": "2027-01-31"},
        )
        party = Party.objects.create(acronym="PT", name="Partido dos Trabalhadores")
        self.parliamentarian = Parliamentarian.objects.create(
            full_name="Maria Silva", gender="F"
        )
        self.term = ParliamentarianTerm.objects.create(
            parliamentarian=self.parliamentarian,
            legislature_number=leg,
            party=party,
            house="camara",
            role="Titular",
            state="SP",
            external_id=1,
            start_date="2023-02-01",
        )

    def test_list_parliamentarians(self):
        response = self.client.get("/api/v1/legislatures/parliamentarians")

        assert response.status_code == 200
        item = response.json()["items"][0]
        assert datetime.fromisoformat(item.pop("created_at")) == self.parliamentarian.created_at.replace(
            microsecond=self.parliamentarian.created_at.microsecond // 1000 * 1000
        )
        assert datetime.fromisoformat(item.pop("updated_at")) == self.parliamentarian.updated_at.replace(
            microsecond=self.parliamentarian.updated_at.microsecond // 1000 * 1000
        )
        assert item == {
            "id": self.parliamentarian.pk,
            "full_name": "Maria Silva",
            "social_name": None,
            "photo_url": None,
            "gender": "F",
            "birth_date": None,
            "race": None,
            "education": None,
            "birthplace": None,
            "profession": None,
            "religion": None,
            "bio": None,
            "public_propositions_count": 0,
            "favorable_propositions_count": 0,
            "unfavorable_propositions_count": 0,
            "terms": [
                {
                    "id": self.term.pk,
                    "parliamentarian": self.parliamentarian.pk,
                    "legislature_number": 57,
                    "party": self.term.party_id,
                    "house": "camara",
                    "role": "Titular",
                    "state": "SP",
                    "external_id": 1,
                    "start_date": "2023-02-01",
                    "end_date": None,
                }
            ],
        }

    def test_get_parliamentarian_detail(self):
        response = self.client.get(
            f"/api/v1/legislatures/parliamentarians/{self.parliamentarian.pk}"
        )
        assert response.status_code == 200
        assert response.json()["public_propositions_count"] == 0
        assert response.json()["favorable_propositions_count"] == 0
        assert response.json()["unfavorable_propositions_count"] == 0

    def test_proposition_counts_for_list_and_detail(self):
        coauthor = Parliamentarian.objects.create(full_name="João Souza", gender="M")
        no_classified_propositions = Parliamentarian.objects.create(full_name="Ana Costa")
        proposition = Proposition.objects.create(
            external_id=1,
            house="camara",
            type_code="pl",
            number_label="PL 123/2024",
            number=123,
            year=2024,
            presented_at="2024-01-01",
            ementa="Test proposition",
            is_approved=True,
        )
        unlabeled_proposition = Proposition.objects.create(
            external_id=2,
            house="camara",
            type_code="pl",
            number_label="PL 124/2024",
            number=124,
            year=2024,
            presented_at="2024-01-02",
            ementa="Unlabeled proposition",
            is_approved=True,
        )
        PropositionAuthor.objects.create(
            proposition=proposition, parliamentarian=self.parliamentarian
        )
        PropositionAuthor.objects.create(proposition=proposition, parliamentarian=coauthor)
        PropositionAuthor.objects.create(
            proposition=unlabeled_proposition,
            parliamentarian=no_classified_propositions,
        )
        first_organization = AssessmentOrganization.objects.create(name="Anis")
        second_organization = AssessmentOrganization.objects.create(name="Themis")
        PropositionAnnotation.objects.create(
            proposition=proposition,
            organization=first_organization,
            is_favorable=True,
            category="saude",
        )
        PropositionAnnotation.objects.create(
            proposition=proposition,
            organization=second_organization,
            is_favorable=True,
            category="saude",
        )
        PropositionAnnotation.objects.create(
            proposition=proposition,
            organization=AssessmentOrganization.objects.create(name="Cfemea"),
            is_favorable=False,
            category="saude",
        )
        PropositionAnnotation.objects.create(
            proposition=unlabeled_proposition,
            organization=AssessmentOrganization.objects.create(name="Instituto"),
            is_favorable=None,
            category="saude",
        )

        response = self.client.get("/api/v1/legislatures/parliamentarians")
        assert response.status_code == 200
        items = {item["id"]: item for item in response.json()["items"]}
        assert items[self.parliamentarian.pk]["favorable_propositions_count"] == 1
        assert items[self.parliamentarian.pk]["unfavorable_propositions_count"] == 1
        assert items[self.parliamentarian.pk]["public_propositions_count"] == 1
        assert items[coauthor.pk]["favorable_propositions_count"] == 1
        assert items[coauthor.pk]["unfavorable_propositions_count"] == 1
        assert items[no_classified_propositions.pk]["favorable_propositions_count"] == 0
        assert items[no_classified_propositions.pk]["unfavorable_propositions_count"] == 0

        detail = self.client.get(
            f"/api/v1/legislatures/parliamentarians/{self.parliamentarian.pk}"
        )
        assert detail.status_code == 200
        assert detail.json()["public_propositions_count"] == 1
        assert detail.json()["favorable_propositions_count"] == 1
        assert detail.json()["unfavorable_propositions_count"] == 1

    def test_ranking_unfavorable_requires_minimum_public_propositions(self):
        second = Parliamentarian.objects.create(full_name="João Souza", gender="M")
        below_minimum = Parliamentarian.objects.create(full_name="Ana Costa", gender="F")
        for person, external_id, state in ((second, 2, "RJ"), (below_minimum, 3, "MG")):
            ParliamentarianTerm.objects.create(
                parliamentarian=person,
                legislature_number=self.term.legislature_number,
                party=self.term.party,
                house="camara",
                role="Titular",
                state=state,
                external_id=external_id,
                start_date="2023-02-01",
            )

        unfavorable_org = AssessmentOrganization.objects.create(name="Anis")

        def create_proposition(external_id, author, *, unfavorable=False, automatic=False):
            proposition = Proposition.objects.create(
                external_id=external_id,
                house="camara",
                type_code="PL",
                number_label=f"PL {external_id}/2026",
                number=external_id,
                year=2026,
                presented_at="2026-01-01",
                ementa="Proposição aprovada sobre direitos de gênero",
                is_approved=True,
            )
            PropositionAuthor.objects.create(proposition=proposition, parliamentarian=author)
            if automatic:
                PropositionAnalysis.objects.create(
                    proposition=proposition,
                    analysis_status=PropositionAnalysis.Status.SUCCEEDED,
                    classification=1 if unfavorable else 0,
                )
            else:
                PropositionAnnotation.objects.create(
                    proposition=proposition,
                    organization=unfavorable_org,
                    is_favorable=not unfavorable,
                    category="saude",
                )

        for external_id in range(10, 16):
            create_proposition(external_id, self.parliamentarian, unfavorable=True)
        for external_id in range(20, 25):
            create_proposition(external_id, second, unfavorable=external_id < 22, automatic=True)
        for external_id in range(30, 34):
            create_proposition(external_id, below_minimum, unfavorable=True)
        unapproved = Proposition.objects.create(
            external_id=40,
            house="camara",
            type_code="PL",
            number_label="PL 40/2026",
            number=40,
            year=2026,
            presented_at="2026-01-01",
            ementa="Proposição ainda pendente de curadoria",
            is_approved=False,
        )
        PropositionAuthor.objects.create(proposition=unapproved, parliamentarian=below_minimum)
        PropositionAnalysis.objects.create(
            proposition=unapproved,
            analysis_status=PropositionAnalysis.Status.SUCCEEDED,
            classification=1,
        )
        unsupported = Proposition.objects.create(
            external_id=41,
            house="camara",
            type_code="SBT",
            number_label="SBT 41/2026",
            number=41,
            year=2026,
            presented_at="2026-01-01",
            ementa="Documento fora do escopo",
            is_approved=True,
        )
        PropositionAuthor.objects.create(proposition=unsupported, parliamentarian=below_minimum)

        response = self.client.get(
            "/api/v1/legislatures/parliamentarians",
            {"current": "true", "rank": "unfavorable", "min_propositions": 5},
        )

        assert response.status_code == 200
        items = response.json()["items"]
        assert [item["id"] for item in items] == [self.parliamentarian.pk, second.pk]
        assert [item["unfavorable_propositions_count"] for item in items] == [6, 2]
        assert [item["public_propositions_count"] for item in items] == [6, 5]


@pytest.mark.django_db
class TestTaxonomyEndpoints:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = Client()

    def test_list_themes(self):
        Theme.objects.create(slug="test", name="Test Theme")
        response = self.client.get("/api/v1/taxonomy/themes")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1


@pytest.mark.django_db
def test_lista_categorias_da_taxonomia_editorial():
    """O modal de alertas monta os checkboxes de tema a partir daqui."""
    response = Client().get("/api/v1/taxonomy/categories")

    assert response.status_code == 200
    categorias = response.json()
    assert {"value": "violencias_de_genero", "label": "Violências de Gênero"} in categorias
    assert len(categorias) == 10


@pytest.mark.django_db
class TestPartiesEndpoints:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = Client()
        Party.objects.create(acronym="PT", name="Partido dos Trabalhadores")

    def test_list_parties(self):
        response = self.client.get("/api/v1/legislatures/parties")
        assert response.status_code == 200


@pytest.mark.django_db
class TestCommitteesEndpoints:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = Client()

    def test_list_committees(self):
        response = self.client.get("/api/v1/committees/")
        assert response.status_code == 200
