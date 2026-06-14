"""Client da API de Dados Abertos do Senado Federal.

Substitui o senado_spider.py (Scrapy/XML) por httpx + JSON.
Três saltos, idênticos ao spider original:
  1. matérias em tramitação na data
  2. detalhe da matéria (assunto, autor, datas)
  3. movimentação da matéria (situação atual)
"""

from collections.abc import Iterator
from datetime import date

from .base import BaseClient

_BASE = "https://legis.senado.leg.br/dadosabertos"


class SenadoClient(BaseClient):
    base_url = _BASE

    def list_materias(self, day: date) -> Iterator[dict]:
        """Itera as matérias em tramitação na data informada.

        A API do Senado aninha as matérias em
        ``ListaMateriasTramitando.Materias.Materia``.
        """
        payload = self.get_json(
            "/materia/tramitando", params={"data": day.strftime("%Y%m%d")}
        )
        materias = (
            payload.get("ListaMateriasTramitando", {})
            .get("Materias", {})
            .get("Materia", [])
        )
        # A API retorna objeto único quando há só uma matéria.
        if isinstance(materias, dict):
            materias = [materias]
        yield from materias

    def fetch_detail(self, materia_id: int) -> dict:
        """Detalhe da matéria (campo ``DetalheMateria.Materia``)."""
        payload = self.get_json(f"/materia/{materia_id}")
        return payload.get("DetalheMateria", {}).get("Materia", {})

    def fetch_movements(self, materia_id: int) -> dict:
        """Situação/movimentação atual da matéria."""
        payload = self.get_json(f"/materia/movimentacoes/{materia_id}")
        return payload.get("MovimentacaoMateria", {})

    def fetch_texts(self, materia_id: int) -> list[dict]:
        """Documentos da matéria (inteiro teor, avulsos, relatórios…).

        Caminho: TextoMateria.Materia.Textos.Texto (objeto único ou lista).
        Cada item traz ``UrlTexto``, ``FormatoTexto``, ``DescricaoTipoTexto``.
        """
        payload = self.get_json(f"/materia/textos/{materia_id}")
        textos = (
            payload.get("TextoMateria", {})
            .get("Materia", {})
            .get("Textos", {})
            .get("Texto", [])
        )
        if isinstance(textos, dict):
            textos = [textos]
        return textos

    def fetch_authors(self, materia_id: int) -> list[dict]:
        """Autores da matéria via serviço de autoria.

        Caminho: AutoriaMateria.Materia.Autoria.Autor (objeto único ou lista).
        Cada autor traz ``IdentificacaoParlamentar`` com sexo, partido e UF.
        """
        payload = self.get_json(f"/materia/autoria/{materia_id}")
        autores = (
            payload.get("AutoriaMateria", {})
            .get("Materia", {})
            .get("Autoria", {})
            .get("Autor", [])
        )
        if isinstance(autores, dict):
            autores = [autores]
        return autores
