from datetime import date

from django.utils import timezone

from apps.core.enums import Gender, House
from apps.ingestion import mappers


class TestHelpers:
    def test_to_int(self):
        assert mappers._to_int("42") == 42
        assert mappers._to_int(7) == 7
        assert mappers._to_int("") is None
        assert mappers._to_int(None) is None
        assert mappers._to_int("abc") is None

    def test_parse_date_formats(self):
        assert mappers._parse_date("2024-03-01") == date(2024, 3, 1)
        assert mappers._parse_date("2024-03-01T10:30:00") == date(2024, 3, 1)
        assert mappers._parse_date("01/03/2024") == date(2024, 3, 1)
        assert mappers._parse_date("") is None
        assert mappers._parse_date("lixo") is None

    def test_parse_datetime_is_aware(self):
        dt = mappers._parse_datetime("2024-03-01T10:30:00")
        assert dt is not None and timezone.is_aware(dt)
        assert mappers._parse_datetime("") is None

    def test_parse_datetime_fallback_to_date(self):
        dt = mappers._parse_datetime("01/03/2024")
        assert dt is not None and dt.year == 2024 and timezone.is_aware(dt)

    def test_first(self):
        assert mappers._first([{"a": 1}, {"a": 2}]) == {"a": 1}
        assert mappers._first([]) == {}
        assert mappers._first({"a": 1}) == {"a": 1}
        assert mappers._first(None) == {}


class TestCamaraMappers:
    def test_proposition_from_fixture(self, camara_payload):
        prop = mappers.map_camara_proposition(
            camara_payload["summary"], camara_payload["detail"], ["útero"]
        )
        assert prop["house"] == House.CAMARA
        assert prop["external_id"] == int(camara_payload["summary"]["id"])
        assert prop["number_label"].startswith(prop["type_code"])
        assert "camara.leg.br" in prop["tramitation_url"]
        assert prop["raw_payload"]["themes"] == ["útero"]

    def test_event_from_fixture(self, camara_payload):
        event = mappers.map_camara_event(camara_payload["detail"])
        assert event is not None
        assert timezone.is_aware(event["event_at"])
        assert event["situation"]

    def test_event_none_without_datahora(self):
        assert mappers.map_camara_event({"statusProposicao": {}}) is None
        assert mappers.map_camara_event({}) is None

    def test_authors_extracts_deputy_id(self):
        authors = mappers.parse_camara_authors(
            [
                {"nome": "Fulana", "tipo": "Deputado(a)", "uri": "https://x/deputados/123"},
                {"nome": "Órgão", "tipo": "Poder Executivo", "uri": None},
            ]
        )
        assert authors[0]["external_id"] == 123
        assert authors[0]["order"] == 1
        assert authors[0]["gender"] is None  # preenchido só no enrich
        assert authors[1]["external_id"] is None

    def test_enrich_author_from_deputy(self):
        author = {"name": "X", "party": None, "state": None, "gender": None}
        deputy = {"sexo": "F", "ultimoStatus": {"siglaPartido": "PT", "siglaUf": "SP"}}
        mappers.enrich_camara_author(author, deputy)
        assert author["gender"] == Gender.F
        assert author["party"] == "PT"
        assert author["state"] == "SP"


class TestMapGender:
    def test_variants(self):
        assert mappers._map_gender("M") == Gender.M
        assert mappers._map_gender("Masculino") == Gender.M
        assert mappers._map_gender("f") == Gender.F
        assert mappers._map_gender("Feminino") == Gender.F
        assert mappers._map_gender(None) is None
        assert mappers._map_gender("X") is None


class TestSenadoMappers:
    def test_proposition_from_fixture(self, senado_payload):
        prop = mappers.map_senado_proposition(
            senado_payload["summary"], senado_payload["detail"], []
        )
        assert prop["house"] == House.SENADO
        assert prop["external_id"]
        assert prop["ementa"]
        assert "senado.leg.br" in prop["tramitation_url"]

    def test_event_from_fixture(self, senado_payload):
        event = mappers.map_senado_event(senado_payload["movements"])
        assert event is not None
        assert event["situation"]
        assert timezone.is_aware(event["event_at"])

    def test_event_none_when_empty(self):
        assert mappers.map_senado_event({}) is None
        assert mappers.map_senado_event({"Materia": {}}) is None

    def test_authors_parses_party_and_state(self, senado_payload):
        authors = mappers.parse_senado_authors(senado_payload["detail"], senado_payload["summary"])
        assert len(authors) == 1
        a = authors[0]
        assert a["kind"] == "parlamentar"
        assert a["party"] and a["state"]
        assert not a["name"].lower().startswith("senador")

    def test_authors_institutional(self):
        detail = {"DadosBasicosMateria": {"Autor": "Comissão de Constituição e Justiça"}}
        authors = mappers.parse_senado_authors(detail)
        assert authors[0]["kind"] == "instituição"
        assert authors[0]["party"] is None

    def test_authors_fallback_to_summary(self):
        authors = mappers.parse_senado_authors({}, {"Autor": "Senadora Maria (PT/SP)"})
        assert authors[0]["name"] == "Maria"
        assert authors[0]["party"] == "PT"
        assert authors[0]["state"] == "SP"

    def test_authors_empty(self):
        assert mappers.parse_senado_authors({}) == []
        assert mappers.parse_senado_authors({"DadosBasicosMateria": {"Autor": "  "}}) == []

    def test_authors_from_autoria_fixture(self, senado_payload):
        autores = senado_payload["autoria"]["AutoriaMateria"]["Materia"]["Autoria"]["Autor"]
        autores = autores if isinstance(autores, list) else [autores]
        out = mappers.parse_senado_authors_from_autoria(autores)
        assert len(out) == 1
        a = out[0]
        assert a["kind"] == "parlamentar"
        assert a["party"] and a["state"]
        assert a["gender"] in (Gender.M, Gender.F)
        assert a["external_id"]

    def test_authors_from_autoria_institutional(self):
        out = mappers.parse_senado_authors_from_autoria(
            [{"NomeAutor": "Poder Executivo", "DescricaoTipoAutor": "Poder Executivo"}]
        )
        assert out[0]["external_id"] is None
        assert out[0]["gender"] is None

    def test_authors_from_autoria_empty(self):
        assert mappers.parse_senado_authors_from_autoria([]) == []
        assert mappers.parse_senado_authors_from_autoria([{"NomeAutor": "  "}]) == []


class TestPickSenadoFullTextUrl:
    def test_from_fixture_picks_pdf(self, senado_payload):
        url = mappers.pick_senado_full_text_url(senado_payload["texts"])
        assert url and "sdleg-getter" in url

    def test_no_texts(self):
        assert mappers.pick_senado_full_text_url([]) is None

    def test_ignores_non_pdf(self):
        texts = [{"UrlTexto": "http://x/doc", "FormatoTexto": "text/html"}]
        assert mappers.pick_senado_full_text_url(texts) is None

    def test_prefers_non_derivative_and_earliest(self):
        texts = [
            {"UrlTexto": "http://x/relatorio", "TipoDocumento": "PDF",
             "DescricaoTipoTexto": "Relatório Legislativo", "DataTexto": "2024-01-01"},
            {"UrlTexto": "http://x/projeto", "TipoDocumento": "PDF",
             "DescricaoTipoTexto": "Projeto de Lei", "DataTexto": "2025-06-01"},
            {"UrlTexto": "http://x/avulso", "TipoDocumento": "PDF",
             "DescricaoTipoTexto": "Avulso inicial", "DataTexto": "2025-03-01"},
        ]
        # não-derivado mais antigo ganha (avulso 2025-03 < projeto 2025-06)
        assert mappers.pick_senado_full_text_url(texts) == "http://x/avulso"

    def test_falls_back_to_derivative_when_only_option(self):
        texts = [{"UrlTexto": "http://x/parecer", "TipoDocumento": "PDF",
                  "DescricaoTipoTexto": "Parecer", "DataTexto": "2024-01-01"}]
        assert mappers.pick_senado_full_text_url(texts) == "http://x/parecer"

    def test_proposition_carries_full_text_url(self, senado_payload):
        prop = mappers.map_senado_proposition(
            senado_payload["summary"], senado_payload["detail"], [], "http://x/doc.pdf"
        )
        assert prop["full_text_url"] == "http://x/doc.pdf"
