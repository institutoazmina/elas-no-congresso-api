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
        por_numero = self.client.get("/api/v1/propositions/?q=PL 123")
        sem_relacao = self.client.get("/api/v1/propositions/?q=zzz-nao-existe")

        assert por_ementa.status_code == 200
        assert [p["number_label"] for p in por_ementa.json()["items"]] == [alvo]
        assert [p["number_label"] for p in por_numero.json()["items"]] == [alvo]
        assert sem_relacao.json()["items"] == []

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
        assert items[coauthor.pk]["favorable_propositions_count"] == 1
        assert items[coauthor.pk]["unfavorable_propositions_count"] == 1
        assert items[no_classified_propositions.pk]["favorable_propositions_count"] == 0
        assert items[no_classified_propositions.pk]["unfavorable_propositions_count"] == 0

        detail = self.client.get(
            f"/api/v1/legislatures/parliamentarians/{self.parliamentarian.pk}"
        )
        assert detail.status_code == 200
        assert detail.json()["favorable_propositions_count"] == 1
        assert detail.json()["unfavorable_propositions_count"] == 1


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
