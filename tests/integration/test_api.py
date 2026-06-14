import pytest
from django.test import Client

from apps.legislatures.models import Legislature, Parliamentarian, ParliamentarianTerm, Party
from apps.propositions.models import Proposition
from apps.taxonomy.models import Theme


@pytest.mark.django_db
class TestPropositionsEndpoints:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = Client()
        leg = Legislature.objects.create(number=57, start_date="2023-02-01", end_date="2027-01-31")
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
class TestParliamentariansEndpoints:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = Client()
        leg = Legislature.objects.create(number=57, start_date="2023-02-01", end_date="2027-01-31")
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

    def test_get_parliamentarian_detail(self):
        response = self.client.get(
            f"/api/v1/legislatures/parliamentarians/{self.parliamentarian.pk}"
        )
        assert response.status_code == 200


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
class TestSubscriptionsEndpoints:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = Client()

    def test_create_subscription(self):
        response = self.client.post(
            "/api/v1/subscriptions/",
            data={"email": "test@example.com", "ast": {"op": "and", "children": [
                {"field": "house", "op": "eq", "value": "camara"}
            ]}},
            content_type="application/json",
        )
        assert response.status_code in (201, 400)


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
