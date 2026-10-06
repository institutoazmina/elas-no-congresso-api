"""Client da API de Dados Abertos do Senado Federal.

Substitui o senado_spider.py (Scrapy/XML) por httpx + JSON.
Três saltos, idênticos ao spider original:
  1. matérias em tramitação na data
  2. detalhe da matéria (assunto, autor, datas)
  3. movimentação da matéria (situação atual)
"""

from collections.abc import Iterator
from datetime import date
from urllib.parse import urljoin

import httpx
from django.utils import timezone
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from apps.ingestion.senado_fronts import (
    SENADO_FRONT_MAX_BYTES,
    SENADO_FRONT_MAX_REDIRECTS,
    SenadoFrontPageLimitError,
    validate_senado_front_url,
)

from .base import BaseClient

_BASE = "https://legis.senado.leg.br/dadosabertos"


class SenadoClient(BaseClient):
    base_url = _BASE

    def list_materias(self, day: date) -> Iterator[dict]:
        """Recent changed processes, including closed matters; preserves legacy identities."""
        days = (timezone.localdate() - day).days + 1
        if days > 30:
            raise ValueError("Senado change feed covers at most 30 days; reconciliation required")
        payload = self.get_json("/processo", params={"numdias": max(1, days), "v": 1})
        if not isinstance(payload, list):
            raise ValueError("Unexpected Senate process listing")
        for process in payload:
            yield {
                "_process_summary": process,
                "Ementa": process.get("ementa", ""),
                "IdentificacaoMateria": {
                    "CodigoMateria": process.get("codigoMateria") or -int(process["id"]),
                    "IdentificacaoProcesso": process["id"],
                },
            }

    def find_process(self, materia_id: int) -> dict | None:
        payload = self.get_json("/processo", params={"codigoMateria": materia_id, "v": 1})
        if not isinstance(payload, list) or len(payload) != 1:
            return None
        return payload[0]

    def fetch_documents(self, process_id: int) -> list[dict]:
        payload = self.get_json("/processo/documento", params={"idProcesso": process_id, "v": 1})
        if not isinstance(payload, list):
            raise ValueError("Unexpected Senate document listing")
        return payload

    def list_current_members(self) -> list[dict]:
        """Lista os senadores em exercício no payload oficial do Senado."""
        payload = self.get_json("/senador/lista/atual")
        root = payload.get("ListaParlamentarEmExercicio", {}) or {}
        parliamentarians = root.get("Parlamentares", {}) or {}
        return _as_list(parliamentarians.get("Parlamentar"))

    def fetch_detail(self, materia_id: int) -> dict:
        """Detalhe da matéria (campo ``DetalheMateria.Materia``)."""
        payload = self.get_json(f"/materia/{materia_id}")
        return payload.get("DetalheMateria", {}).get("Materia", {})

    def fetch_movements(self, materia_id: int) -> dict:
        """Situação/movimentação atual da matéria."""
        payload = self.get_json(f"/materia/movimentacoes/{materia_id}")
        return payload.get("MovimentacaoMateria", {})

    def fetch_process(self, process_id: int) -> dict:
        """Linha do tempo da matéria no serviço substituto do Senado."""
        return self.get_json(f"/processo/{process_id}")

    def fetch_texts(self, materia_id: int) -> list[dict]:
        """Documentos da matéria (inteiro teor, avulsos, relatórios…).

        Caminho: TextoMateria.Materia.Textos.Texto (objeto único ou lista).
        Cada item traz ``UrlTexto``, ``FormatoTexto``, ``DescricaoTipoTexto``.
        """
        payload = self.get_json(f"/materia/textos/{materia_id}")
        textos = (
            payload.get("TextoMateria", {}).get("Materia", {}).get("Textos", {}).get("Texto", [])
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
            payload.get("AutoriaMateria", {}).get("Materia", {}).get("Autoria", {}).get("Autor", [])
        )
        if isinstance(autores, dict):
            autores = [autores]
        return autores

    def fetch_profile(self, senator_id: int) -> dict:
        """Perfil oficial de um senador, sem os envelopes da resposta."""
        payload = self.get_json(f"/senador/{senator_id}")
        return payload.get("DetalheParlamentar", {}).get("Parlamentar", {})

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def fetch_front_html(
        self,
        url: str,
        *,
        max_bytes: int = SENADO_FRONT_MAX_BYTES,
        max_redirects: int = SENADO_FRONT_MAX_REDIRECTS,
    ) -> str:
        current_url = validate_senado_front_url(url)
        for redirect_count in range(max_redirects + 1):
            with self._client.stream(
                "GET",
                current_url,
                follow_redirects=False,
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    if redirect_count >= max_redirects:
                        raise SenadoFrontPageLimitError("Senado front redirect limit exceeded")
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Senado front redirect has no location")
                    current_url = validate_senado_front_url(urljoin(current_url, location))
                    continue

                response.raise_for_status()
                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        if int(content_length) > max_bytes:
                            raise SenadoFrontPageLimitError(
                                "Senado front response exceeds byte limit"
                            )
                    except ValueError:
                        pass

                payload = bytearray()
                for chunk in response.iter_bytes():
                    payload.extend(chunk)
                    if len(payload) > max_bytes:
                        raise SenadoFrontPageLimitError("Senado front response exceeds byte limit")
                encoding = response.encoding or "utf-8"
                return bytes(payload).decode(encoding, errors="replace")
        raise SenadoFrontPageLimitError("Senado front redirect limit exceeded")

    def fetch_senator_committees(self, senator_id: int) -> list[dict]:
        """Comissões do senador, com a forma singleton/lista normalizada."""
        return self._fetch_senator_collection(
            senator_id, "comissoes", "ComissoesParlamentar", "Comissoes", "Comissao"
        )

    def fetch_senator_party_affiliations(self, senator_id: int) -> list[dict]:
        """Filiações partidárias do senador, com a forma singleton/lista normalizada."""
        return self._fetch_senator_collection(
            senator_id,
            "filiacoes",
            "FiliacoesPartidariasParlamentar",
            "Filiacoes",
            "FiliacaoPartidaria",
        )

    def fetch_senator_leaderships(self, senator_id: int) -> list[dict]:
        """Lideranças do senador, com a forma singleton/lista normalizada."""
        return self._fetch_senator_collection(
            senator_id, "liderancas", "LiderancasParlamentar", "Liderancas", "Lideranca"
        )

    def fetch_senator_posts(self, senator_id: int) -> list[dict]:
        """Cargos/postos do senador, com a forma singleton/lista normalizada."""
        return self._fetch_senator_collection(
            senator_id, "cargos", "CargosParlamentar", "Cargos", "Cargo"
        )

    def fetch_senator_professions(self, senator_id: int) -> list[dict]:
        """Profissões declaradas pelo senador."""
        return self._fetch_senator_collection(
            senator_id,
            "profissao",
            "HistoricoAcademicoParlamentar",
            "Profissoes",
            "Profissao",
        )

    def fetch_senator_academic_history(self, senator_id: int) -> list[dict]:
        """Histórico acadêmico declarado pelo senador."""
        return self._fetch_senator_collection(
            senator_id,
            "historicoAcademico",
            "HistoricoAcademicoParlamentar",
            "HistoricoAcademico",
            "Curso",
        )

    def _fetch_senator_collection(
        self,
        senator_id: int,
        endpoint: str,
        root: str,
        collection: str,
        item: str,
    ) -> list[dict]:
        payload = self.get_json(f"/senador/{senator_id}/{endpoint}")
        root_payload = payload.get(root, {}) or {}
        parliamentarian = root_payload.get("Parlamentar", {}) or {}
        collection_payload = parliamentarian.get(collection, {}) or {}
        return _as_list(collection_payload.get(item))


def _as_list(value) -> list[dict]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []
