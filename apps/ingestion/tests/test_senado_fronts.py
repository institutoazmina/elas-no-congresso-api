import httpx
import pytest

from apps.ingestion import tasks
from apps.ingestion.clients.senado import SenadoClient, SenadoFrontPageLimitError
from apps.ingestion.senado_fronts import (
    SenadoFrontScrapeResult,
    UnsafeSenadoFrontUrl,
    parse_senado_front_catalog,
    parse_senado_front_composition,
    parse_senado_front_council,
    scrape_senado_fronts,
)

CATALOG_URL = "https://www25.senado.leg.br/web/atividade/conselhos/-/conselho/frentes-parlamentares"
COUNCIL_URL = "https://www25.senado.leg.br/web/atividade/conselhos/-/conselho/fpc"
COMPOSITION_URL = "https://legis.senado.leg.br/comissoes/composicao_comissao?codcol=2696"

CATALOG_HTML = """
<table>
  <tr><th>Nome</th><th>Sigla</th><th>Situação</th></tr>
  <tr>
    <td><a href="/web/atividade/conselhos/-/conselho/fpc">Frente Parlamentar de Cuidado</a></td>
    <td>FPC</td><td>Ativa</td>
  </tr>
</table>
"""
COUNCIL_HTML = f"""
<h1>Frente Parlamentar de Cuidado</h1>
<a href="{COMPOSITION_URL}">Composição</a>
"""
COMPOSITION_HTML = """
<table>
  <tr><th>Parlamentar</th><th>Função</th></tr>
  <tr>
    <td><a href="https://www25.senado.leg.br/web/senadores/senador/-/perfil/35">Senadora Um</a></td>
    <td>Presidente</td>
  </tr>
  <tr>
    <td><a href="https://www.camara.leg.br/deputados/204554">Deputada Dois</a></td>
    <td>Membro</td>
  </tr>
</table>
"""


def test_parsers_extract_front_identity_composition_and_profile_ids():
    entries = parse_senado_front_catalog(CATALOG_HTML, catalog_url=CATALOG_URL)
    assert len(entries) == 1
    assert entries[0].name == "Frente Parlamentar de Cuidado"
    assert entries[0].acronym == "FPC"
    assert entries[0].status == "Ativa"
    assert entries[0].council_url == COUNCIL_URL

    front = parse_senado_front_council(entries[0], COUNCIL_HTML)
    assert front.codcol == "2696"
    assert front.composition_url == COMPOSITION_URL

    members = parse_senado_front_composition(COMPOSITION_HTML, COMPOSITION_URL)
    assert [(member.house, member.external_id) for member in members] == [
        ("senado", 35),
        ("camara", 204554),
    ]
    assert members[0].role == "Presidente"


def test_parser_rejects_untrusted_front_urls():
    malicious = CATALOG_HTML.replace(
        "/web/atividade/conselhos/-/conselho/fpc",
        "https://evil.example/web/atividade/conselhos/-/conselho/fpc",
    )

    with pytest.raises(UnsafeSenadoFrontUrl):
        parse_senado_front_catalog(malicious, catalog_url=CATALOG_URL)


def test_parser_enforces_front_count_bound():
    with pytest.raises(SenadoFrontPageLimitError):
        parse_senado_front_catalog(CATALOG_HTML, catalog_url=CATALOG_URL, max_fronts=0)


def test_scraper_isolates_failed_front_pages_and_keeps_successful_snapshot():
    class _Client:
        def __init__(self):
            self.requested = []

        def fetch_front_html(self, url, **kwargs):
            self.requested.append(url)
            if url == COUNCIL_URL:
                return COUNCIL_HTML
            return COMPOSITION_HTML

    client = _Client()
    snapshot = scrape_senado_fronts(
        client,
        catalog_url=CATALOG_URL,
        max_pages=3,
        max_fronts=1,
        catalog_html=CATALOG_HTML,
    )

    assert isinstance(snapshot, SenadoFrontScrapeResult)
    assert snapshot.failed_fronts == 0
    assert len(snapshot.fronts) == 1
    assert client.requested == [COUNCIL_URL, COMPOSITION_URL]


def test_scraper_counts_a_failed_front_without_blocking_another():
    catalog = CATALOG_HTML.replace(
        "</table>",
        '<tr><td><a href="/web/atividade/conselhos/-/conselho/bad">Outra Frente</a></td>'
        "<td>OFR</td><td>Ativa</td></tr></table>",
    )

    class _Client:
        def fetch_front_html(self, url, **kwargs):
            if url.endswith("/bad"):
                raise RuntimeError("front unavailable")
            if url == COUNCIL_URL:
                return COUNCIL_HTML
            return COMPOSITION_HTML

    snapshot = scrape_senado_fronts(
        _Client(),
        catalog_url=CATALOG_URL,
        max_pages=5,
        max_fronts=2,
        catalog_html=catalog,
    )

    assert len(snapshot.fronts) == 1
    assert snapshot.failed_fronts == 1


def test_senado_front_client_rejects_oversized_html_response():
    client = SenadoClient(
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"12345"))
        )
    )

    with pytest.raises(SenadoFrontPageLimitError):
        client.fetch_front_html(CATALOG_URL, max_bytes=4)


def test_senado_front_client_validates_redirect_targets():
    client = SenadoClient(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    302,
                    headers={"location": "https://evil.example/front"},
                )
            )
        )
    )

    with pytest.raises(UnsafeSenadoFrontUrl):
        client.fetch_front_html(CATALOG_URL)


def test_scraper_enforces_page_bound_without_fetching_a_front():
    requested = []

    class _Client:
        def fetch_front_html(self, url, **kwargs):
            requested.append(url)
            return COUNCIL_HTML

    result = scrape_senado_fronts(
        _Client(),
        catalog_url=CATALOG_URL,
        max_pages=1,
        max_fronts=1,
        catalog_html=CATALOG_HTML,
    )

    assert result.fronts == ()
    assert result.failed_fronts == 1
    assert requested == []


def test_task_front_loader_builds_snapshot_once(monkeypatch):
    calls = []

    class _Client:
        def __enter__(self):
            calls.append("enter")
            return self

        def __exit__(self, *exc):
            return False

        def fetch_front_html(self, url, **kwargs):
            calls.append(url)
            if url == CATALOG_URL:
                return CATALOG_HTML
            if url == COUNCIL_URL:
                return COUNCIL_HTML
            return COMPOSITION_HTML

    monkeypatch.setattr(tasks, "SenadoClient", _Client)
    monkeypatch.setattr(tasks.settings, "SENADO_FRONT_CATALOG_URL", CATALOG_URL)

    snapshot = tasks._load_senado_front_snapshot()

    assert len(snapshot.fronts) == 1
    assert calls == ["enter", CATALOG_URL, COUNCIL_URL, COMPOSITION_URL]
