from datetime import date

import httpx
import pytest

from apps.ingestion.clients.base import BaseClient
from apps.ingestion.clients.camara import CamaraClient, _next_link
from apps.ingestion.clients.senado import SenadoClient


def _client_for(cls, handler):
    inner = httpx.Client(transport=httpx.MockTransport(handler), base_url=cls.base_url)
    return cls(client=inner)


class TestBaseClient:
    def test_get_json_success(self):
        c = _client_for(CamaraClient, lambda r: httpx.Response(200, json={"ok": 1}))
        assert c.get_json("/x") == {"ok": 1}

    def test_retry_then_success(self, monkeypatch):
        monkeypatch.setattr("time.sleep", lambda *a, **k: None)
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ConnectError("transient")
            return httpx.Response(200, json={"ok": True})

        c = _client_for(CamaraClient, handler)
        assert c.get_json("/x") == {"ok": True}
        assert calls["n"] == 2

    def test_retry_exhausted_reraises(self, monkeypatch):
        monkeypatch.setattr("time.sleep", lambda *a, **k: None)

        def handler(request):
            raise httpx.ConnectError("always down")

        c = _client_for(CamaraClient, handler)
        with pytest.raises(httpx.ConnectError):
            c.get_json("/x")

    def test_status_error_is_retryable(self, monkeypatch):
        monkeypatch.setattr("time.sleep", lambda *a, **k: None)
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(500)

        c = _client_for(CamaraClient, handler)
        with pytest.raises(httpx.HTTPStatusError):
            c.get_json("/x")
        assert calls["n"] == 3  # stop_after_attempt(3)

    def test_context_manager_closes_owned_client(self):
        with BaseClient() as c:
            assert c._owns_client is True
        assert c._client.is_closed


class TestCamaraClient:
    def test_next_link(self):
        assert _next_link([{"rel": "self", "href": "a"}, {"rel": "next", "href": "b"}]) == "b"
        assert _next_link([{"rel": "self", "href": "a"}]) is None

    def test_list_propositions_paginates(self):
        def handler(request):
            if "pagina=2" in str(request.url):
                return httpx.Response(200, json={"dados": [{"id": 2}], "links": []})
            return httpx.Response(
                200,
                json={
                    "dados": [{"id": 1}],
                    "links": [{"rel": "next", "href": f"{CamaraClient.base_url}/proposicoes?pagina=2"}],
                },
            )

        c = _client_for(CamaraClient, handler)
        ids = [p["id"] for p in c.list_propositions(date(2024, 1, 1), date(2024, 1, 2))]
        assert ids == [1, 2]

    def test_fetch_detail_and_authors(self):
        def handler(request):
            if request.url.path.endswith("/autores"):
                return httpx.Response(200, json={"dados": [{"nome": "X"}]})
            return httpx.Response(200, json={"dados": {"id": 9}})

        c = _client_for(CamaraClient, handler)
        assert c.fetch_detail(9) == {"id": 9}
        assert c.fetch_authors(9) == [{"nome": "X"}]


class TestSenadoClient:
    def test_list_materias_normalizes_single(self):
        def handler(request):
            return httpx.Response(
                200,
                json={"ListaMateriasTramitando": {"Materias": {"Materia": {"x": 1}}}},
            )

        c = _client_for(SenadoClient, handler)
        assert list(c.list_materias(date(2024, 1, 1))) == [{"x": 1}]

    def test_list_materias_list(self):
        def handler(request):
            return httpx.Response(
                200,
                json={"ListaMateriasTramitando": {"Materias": {"Materia": [{"x": 1}, {"x": 2}]}}},
            )

        c = _client_for(SenadoClient, handler)
        assert len(list(c.list_materias(date(2024, 1, 1)))) == 2

    def test_list_materias_empty(self):
        c = _client_for(SenadoClient, lambda r: httpx.Response(200, json={}))
        assert list(c.list_materias(date(2024, 1, 1))) == []

    def test_fetch_detail_and_movements(self):
        def handler(request):
            if "movimentacoes" in request.url.path:
                return httpx.Response(200, json={"MovimentacaoMateria": {"Materia": {"m": 1}}})
            return httpx.Response(200, json={"DetalheMateria": {"Materia": {"d": 1}}})

        c = _client_for(SenadoClient, handler)
        assert c.fetch_detail(5) == {"d": 1}
        assert c.fetch_movements(5) == {"Materia": {"m": 1}}

    def test_fetch_texts_normalizes_single(self):
        def handler(request):
            return httpx.Response(
                200,
                json={"TextoMateria": {"Materia": {"Textos": {"Texto": {"UrlTexto": "u"}}}}},
            )

        c = _client_for(SenadoClient, handler)
        assert c.fetch_texts(7) == [{"UrlTexto": "u"}]

    def test_fetch_texts_list_and_empty(self):
        def handler(request):
            return httpx.Response(
                200,
                json={"TextoMateria": {"Materia": {"Textos": {"Texto": [{"a": 1}, {"a": 2}]}}}},
            )

        c = _client_for(SenadoClient, handler)
        assert len(c.fetch_texts(7)) == 2

        empty = _client_for(SenadoClient, lambda r: httpx.Response(200, json={}))
        assert empty.fetch_texts(7) == []
