from apps.ingestion.parliamentarians import normalize_camara_profile, normalize_senado_profile


class TestNormalizeCamaraProfile:
    def test_maps_official_profile_fields(self, camara_payload):
        assert normalize_camara_profile(camara_payload["deputy"]) == {
            "external_id": 204554,
            "full_name": "JOSE ABILIO SILVA DE SANTANA",
            "social_name": "Abílio Santana",
            "gender": "M",
            "photo_url": "https://www.camara.leg.br/internet/deputado/bandep/204554.jpg",
            "birthplace": "Salvador, BA",
        }

    def test_maps_missing_values_to_none(self):
        assert normalize_camara_profile({}) == {
            "external_id": None,
            "full_name": None,
            "social_name": None,
            "gender": None,
            "photo_url": None,
            "birthplace": None,
        }

    def test_limits_gender_to_existing_values(self):
        assert normalize_camara_profile({"sexo": "Feminino"})["gender"] == "F"
        assert normalize_camara_profile({"sexo": "outro"})["gender"] is None


class TestNormalizeSenadoProfile:
    def test_maps_official_profile_fields(self):
        profile = {
            "IdentificacaoParlamentar": {
                "CodigoParlamentar": "35",
                "NomeParlamentar": "Jader Barbalho",
                "NomeCompletoParlamentar": "Jader Fontenelle Barbalho",
                "SexoParlamentar": "Masculino",
                "UrlFotoParlamentar": "http://www.senado.leg.br/senadores/img/fotos-oficiais/senador35.jpg",
            },
            "DadosBasicosParlamentar": {
                "Naturalidade": "Caxias do Sul",
                "UfNaturalidade": "RS",
            },
        }

        assert normalize_senado_profile(profile) == {
            "external_id": 35,
            "full_name": "Jader Fontenelle Barbalho",
            "social_name": "Jader Barbalho",
            "gender": "M",
            "photo_url": "http://www.senado.leg.br/senadores/img/fotos-oficiais/senador35.jpg",
            "birthplace": "Caxias do Sul, RS",
        }

    def test_maps_missing_values_to_none(self):
        assert normalize_senado_profile({}) == {
            "external_id": None,
            "full_name": None,
            "social_name": None,
            "gender": None,
            "photo_url": None,
            "birthplace": None,
        }

    def test_limits_gender_to_existing_values(self):
        assert normalize_senado_profile(
            {"IdentificacaoParlamentar": {"SexoParlamentar": "Feminino"}}
        )["gender"] == "F"
        assert normalize_senado_profile(
            {"IdentificacaoParlamentar": {"SexoParlamentar": "Não informado"}}
        )["gender"] is None
