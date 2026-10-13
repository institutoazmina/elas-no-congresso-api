"""Defesas da API pública: identidade do cliente, limites, tetos de entrada e
cabeçalhos de cache para a CDN.

O projeto é alvo provável em eleição polarizada; cada teste aqui descreve um
abuso concreto que a API precisa aguentar sem cair nem servir dado errado.
"""

import pytest
from django.core.cache import cache
from django.test import Client, RequestFactory

from apps.core.throttling import client_ip
from apps.propositions import dataset

CATEGORIES = "/api/v1/taxonomy/categories"


@pytest.fixture(autouse=True)
def _cache_limpo():
    """O throttle vive no cache e o locmem sobrevive entre testes."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def client():
    return Client()


# ── identidade do cliente ─────────────────────────────────────────────────────


def test_x_forwarded_for_nao_define_identidade(settings):
    settings.TRUST_CF_CONNECTING_IP = True
    request = RequestFactory().get(
        "/", REMOTE_ADDR="172.17.0.1", HTTP_X_FORWARDED_FOR="1.2.3.4, 198.51.100.7"
    )

    assert client_ip(request) == "172.17.0.1"


def test_cf_connecting_ip_vale_quando_a_origem_so_e_alcancavel_pelo_cloudflare(settings):
    settings.TRUST_CF_CONNECTING_IP = True
    request = RequestFactory().get(
        "/", REMOTE_ADDR="172.17.0.1", HTTP_CF_CONNECTING_IP="198.51.100.7"
    )

    assert client_ip(request) == "198.51.100.7"


def test_cf_connecting_ip_e_ignorado_sem_confianca_configurada(settings):
    settings.TRUST_CF_CONNECTING_IP = False
    request = RequestFactory().get(
        "/", REMOTE_ADDR="203.0.113.9", HTTP_CF_CONNECTING_IP="198.51.100.7"
    )

    assert client_ip(request) == "203.0.113.9"


# ── limite geral ──────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_limite_geral_barra_rajada_do_mesmo_ip(client, settings):
    settings.API_THROTTLE_RATE = "3/m"

    status = [client.get(CATEGORIES).status_code for _ in range(4)]

    assert status == [200, 200, 200, 429]


@pytest.mark.django_db
def test_x_forwarded_for_forjado_nao_renova_a_cota(client, settings):
    settings.API_THROTTLE_RATE = "2/m"
    settings.TRUST_CF_CONNECTING_IP = True

    status = [
        client.get(CATEGORIES, HTTP_X_FORWARDED_FOR=f"10.0.0.{i}").status_code for i in range(3)
    ]

    assert status == [200, 200, 429]


@pytest.mark.django_db
def test_cada_cliente_real_tem_cota_propria(client, settings):
    settings.API_THROTTLE_RATE = "1/m"
    settings.TRUST_CF_CONNECTING_IP = True

    primeiro = client.get(CATEGORIES, HTTP_CF_CONNECTING_IP="198.51.100.1")
    barrado = client.get(CATEGORIES, HTTP_CF_CONNECTING_IP="198.51.100.1")
    outro = client.get(CATEGORIES, HTTP_CF_CONNECTING_IP="198.51.100.2")

    assert [primeiro.status_code, barrado.status_code, outro.status_code] == [200, 429, 200]


@pytest.mark.django_db
def test_resposta_barrada_nao_vira_cache_publico(client, settings):
    settings.API_THROTTLE_RATE = "1/m"
    client.get(CATEGORIES)

    response = client.get(CATEGORIES)

    assert response.status_code == 429
    assert "public" not in response.get("Cache-Control", "")


# ── exportações ───────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_exportacao_do_explorer_tem_cota_propria_e_estrita(client, settings):
    settings.EXPORT_THROTTLE_RATE = "1/h"

    primeira = client.get("/api/v1/activity/explorer/export")
    segunda = client.get("/api/v1/activity/explorer/export")
    explorer = client.get("/api/v1/activity/explorer")

    assert [primeira.status_code, segunda.status_code] == [200, 429]
    assert explorer.status_code == 200


@pytest.mark.django_db
def test_download_do_dataset_tem_cota_estrita(client, settings):
    settings.DATASET_DOWNLOAD_THROTTLE_RATE = "1/h"

    primeiro = client.get("/api/v1/dataset/download?format=jsonl")
    b"".join(primeiro.streaming_content)
    primeiro.close()
    segundo = client.get("/api/v1/dataset/download?format=jsonl")

    assert [primeiro.status_code, segundo.status_code] == [200, 429]


@pytest.mark.django_db
def test_so_um_download_do_dataset_por_vez(client):
    em_andamento = client.get("/api/v1/dataset/download?format=csv")

    concorrente = client.get("/api/v1/dataset/download?format=parquet")

    assert em_andamento.status_code == 200
    assert concorrente.status_code == 503


@pytest.mark.django_db
@pytest.mark.parametrize("fmt", ["csv", "jsonl", "parquet"])
def test_download_libera_a_vez_ao_terminar_o_envio(client, fmt):
    response = client.get(f"/api/v1/dataset/download?format={fmt}")
    if response.streaming:
        b"".join(response.streaming_content)
    response.close()

    assert response.status_code == 200
    assert cache.get(dataset.DOWNLOAD_LOCK_KEY) is None


@pytest.mark.django_db
def test_download_abandonado_antes_de_ler_tambem_libera_a_vez(client):
    response = client.get("/api/v1/dataset/download?format=csv")

    response.close()

    assert cache.get(dataset.DOWNLOAD_LOCK_KEY) is None


@pytest.mark.django_db
def test_formato_invalido_nao_prende_a_vez(client):
    response = client.get("/api/v1/dataset/download?format=xlsx")

    assert response.status_code == 400
    assert cache.get(dataset.DOWNLOAD_LOCK_KEY) is None


# ── tetos de entrada ──────────────────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("path", "limit", "status"),
    [
        ("/api/v1/dataset/", 100, 200),
        ("/api/v1/dataset/", 101, 422),
        ("/api/v1/propositions/", 1000, 200),
        ("/api/v1/propositions/", 1001, 422),
    ],
)
def test_paginacao_tem_teto(client, path, limit, status):
    assert client.get(path, {"limit": limit}).status_code == status


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("path", "param"),
    [
        ("/api/v1/propositions/", "q"),
        ("/api/v1/norms/", "q"),
        ("/api/v1/activity/explorer", "search"),
    ],
)
def test_busca_tem_tamanho_maximo(client, path, param):
    assert client.get(path, {param: "a" * 200}).status_code == 200
    assert client.get(path, {param: "a" * 201}).status_code == 422


@pytest.mark.django_db
def test_filtro_multiplo_tem_quantidade_maxima(client):
    ok = client.get("/api/v1/activity/explorer", {"party": [f"P{i}" for i in range(100)]})
    excesso = client.get("/api/v1/activity/explorer", {"party": [f"P{i}" for i in range(101)]})

    assert ok.status_code == 200
    assert excesso.status_code == 422


# ── cache HTTP ────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_leitura_publica_e_cacheavel_pela_cdn(client, settings):
    settings.PUBLIC_CACHE_MAX_AGE = 60
    settings.PUBLIC_CACHE_S_MAXAGE = 300
    settings.PUBLIC_CACHE_STALE_WHILE_REVALIDATE = 600

    response = client.get(CATEGORIES)

    directives = {d.strip() for d in response["Cache-Control"].split(",")}
    assert directives == {
        "public",
        "max-age=60",
        "s-maxage=300",
        "stale-while-revalidate=600",
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/subscriptions/confirm/token-inexistente"),
        ("get", "/api/v1/subscriptions/unsubscribe/token-inexistente"),
        ("get", "/api/v1/propositions/999999999"),
        ("post", "/api/v1/subscriptions/"),
        ("get", "/health/"),
    ],
)
def test_respostas_privadas_ou_de_erro_nao_viram_cache_publico(client, method, path):
    response = getattr(client, method)(path)

    assert "public" not in response.get("Cache-Control", "")


# ── teto de duração das queries ───────────────────────────────────────────────


def _statement_timeout():
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SHOW statement_timeout")
        return cursor.fetchone()[0]


@pytest.mark.django_db
def test_processo_web_aplica_teto_de_query_na_conexao(settings):
    from django.db import connection

    from config.db import apply_statement_timeout

    settings.DB_STATEMENT_TIMEOUT_MS = 1500
    apply_statement_timeout(sender=None, connection=connection)

    assert _statement_timeout() == "1500ms"


@pytest.mark.django_db
def test_teto_de_query_desligado_nao_mexe_na_conexao(settings):
    from django.db import connection

    from config.db import apply_statement_timeout

    antes = _statement_timeout()
    settings.DB_STATEMENT_TIMEOUT_MS = 0
    apply_statement_timeout(sender=None, connection=connection)

    assert _statement_timeout() == antes


@pytest.mark.django_db
def test_entrypoint_asgi_liga_o_teto_em_conexoes_novas(settings):
    """Workers e ``manage.py migrate`` carregam o mesmo settings; só o
    entrypoint ASGI conecta o handler."""
    from django.db import connection
    from django.db.backends.signals import connection_created

    import config.asgi  # noqa: F401

    settings.DB_STATEMENT_TIMEOUT_MS = 2500
    connection_created.send(sender=type(connection), connection=connection)

    assert _statement_timeout() == "2500ms"
