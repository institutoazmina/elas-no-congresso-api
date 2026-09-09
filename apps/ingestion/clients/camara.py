"""Client da API de Dados Abertos da Câmara dos Deputados.

Substitui o camara_spider.py (Scrapy/XML) por httpx + JSON.
Três saltos, idênticos ao spider original:
  1. lista paginada de proposições na janela de datas
  2. detalhe da proposição (status, urls, inteiro teor)
  3. autores da proposição
"""

from collections.abc import Iterator
from datetime import date

from .base import BaseClient

_BASE = "https://dadosabertos.camara.leg.br/api/v2"


class CamaraClient(BaseClient):
    base_url = _BASE

    def list_propositions(self, start: date, end: date) -> Iterator[dict]:
        """Itera todas as proposições apresentadas na janela [start, end].

        Yields o resumo de cada proposição (id, tipo, número, ano, ementa, uri).
        Pagina seguindo os links ``rel=next``.
        """
        params = {
            "dataInicio": start.isoformat(),
            "dataFim": end.isoformat(),
            "ordem": "ASC",
            "ordenarPor": "id",
            "itens": 100,
        }
        url = "/proposicoes"
        while url:
            payload = self.get_json(url, params=params)
            yield from payload.get("dados", [])
            url = _next_link(payload.get("links", []))
            params = None  # o link `next` já carrega a querystring

    def fetch_detail(self, proposition_id: int) -> dict:
        """Detalhe completo da proposição (campo ``dados``)."""
        return self.get_json(f"/proposicoes/{proposition_id}").get("dados", {})

    def fetch_authors(self, proposition_id: int) -> list[dict]:
        """Lista de autores da proposição."""
        return self.get_json(f"/proposicoes/{proposition_id}/autores").get("dados", [])

    def fetch_deputy(self, deputy_id: int) -> dict:
        """Detalhe de um deputado (traz ``sexo`` e ``ultimoStatus.siglaPartido``)."""
        return self.get_json(f"/deputados/{deputy_id}").get("dados", {})

    def fetch_profile(self, deputy_id: int) -> dict:
        """Perfil oficial de um deputado, sem o envelope ``dados``."""
        return self.fetch_deputy(deputy_id)

    def fetch_deputy_fronts(self, deputy_id: int) -> list[dict]:
        """Frentes parlamentares de um deputado, como uma lista de registros."""
        payload = self.get_json(f"/deputados/{deputy_id}/frentes")
        return _as_list(payload.get("dados"))

    def fetch_deputy_organs(self, deputy_id: int) -> list[dict]:
        """Órgãos dos quais um deputado participa, como uma lista de registros."""
        payload = self.get_json(f"/deputados/{deputy_id}/orgaos")
        return _as_list(payload.get("dados"))


def _next_link(links: list[dict]) -> str | None:
    for link in links:
        if link.get("rel") == "next":
            return link.get("href")
    return None


def _as_list(value) -> list[dict]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []
