"""Comportamento do endpoint público de inscrição em alertas.

O site é estático e vive em outro domínio, então tudo aqui é exercitado como o
browser faria: cross-origin, com o payload que o modal monta.
"""

import pytest
from django.test import Client

from apps.propositions.models import Proposition
from apps.subscriptions.models import Subscription
from apps.subscriptions.tasks import match_and_notify, send_daily_digest

SITE_ORIGIN = "https://www.elasnocongresso.com.br"
HOMOLOGATION_ORIGIN = "https://homologacao.elasnocongresso.com.br"


@pytest.fixture(autouse=True)
def _cache_limpo():
    """O throttle vive no cache e o locmem sobrevive entre testes."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def client():
    return Client()


def _make_subscription(**kwargs):
    defaults = {
        "email": "alguem@example.com",
        "ast": {},
        "query": "casa_camara",
        "is_active": False,
    }
    defaults.update(kwargs)
    return Subscription.objects.create(**defaults)


@pytest.mark.django_db
def test_preflight_do_site_e_liberado(client):
    response = client.options(
        "/api/v1/subscriptions/",
        HTTP_ORIGIN=SITE_ORIGIN,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type",
    )

    assert response.status_code == 200
    assert response["Access-Control-Allow-Origin"] == SITE_ORIGIN


@pytest.mark.django_db
def test_requisicao_da_homologacao_e_liberada(client):
    response = client.get(
        "/api/v1/propositions/?q=saude",
        HTTP_ORIGIN=HOMOLOGATION_ORIGIN,
    )

    assert response.status_code == 200
    assert response["Access-Control-Allow-Origin"] == HOMOLOGATION_ORIGIN


@pytest.mark.django_db
def test_preflight_de_origem_desconhecida_nao_ganha_header(client):
    response = client.options(
        "/api/v1/subscriptions/",
        HTTP_ORIGIN="https://evil.example.com",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
    )

    assert "Access-Control-Allow-Origin" not in response


@pytest.mark.django_db
def test_busca_de_proposicoes_tambem_responde_ao_site(client):
    """O campo de proposição do modal consulta a API em runtime."""
    response = client.get("/api/v1/propositions/?q=saude", HTTP_ORIGIN=SITE_ORIGIN)

    assert response.status_code == 200
    assert response["Access-Control-Allow-Origin"] == SITE_ORIGIN


@pytest.mark.django_db
def test_admin_nao_responde_cross_origin(client):
    response = client.get("/admin/", HTTP_ORIGIN=SITE_ORIGIN)

    assert "Access-Control-Allow-Origin" not in response


@pytest.mark.parametrize("name", ["daily-header.png", "header.png"])
def test_asset_do_email_e_publico_e_cacheavel(client, name):
    response = client.get(f"/api/v1/assets/emails/{name}")

    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    assert response["Cache-Control"] == "public, max-age=31536000, immutable"
    assert b"".join(response.streaming_content).startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize("name", ["inexistente.png", "weekly-header.png"])
def test_asset_de_email_desconhecido_retorna_404(client, name):
    response = client.get(f"/api/v1/assets/emails/{name}")

    assert response.status_code == 404


@pytest.mark.django_db
def test_clicar_no_link_de_confirmacao_ativa_e_devolve_ao_site(client, settings):
    settings.PUBLIC_SITE_URL = SITE_ORIGIN
    sub = _make_subscription()

    response = client.get(f"/api/v1/subscriptions/confirm/{sub.confirm_token}")

    assert response.status_code == 302
    assert response["Location"] == f"{SITE_ORIGIN}/?subscription=confirmado"
    sub.refresh_from_db()
    assert sub.is_active
    assert sub.confirmed_at is not None


@pytest.mark.django_db
def test_link_de_confirmacao_invalido_devolve_ao_site_sinalizando_erro(client, settings):
    settings.PUBLIC_SITE_URL = SITE_ORIGIN

    response = client.get("/api/v1/subscriptions/confirm/token-que-nao-existe")

    assert response.status_code == 302
    assert response["Location"] == f"{SITE_ORIGIN}/?subscription=invalido"


@pytest.mark.django_db
def test_clicar_no_link_de_cancelamento_desativa_e_devolve_ao_site(client, settings):
    settings.PUBLIC_SITE_URL = SITE_ORIGIN
    sub = _make_subscription(is_active=True)

    response = client.get(f"/api/v1/subscriptions/unsubscribe/{sub.unsubscribe_token}")

    assert response.status_code == 302
    assert response["Location"] == f"{SITE_ORIGIN}/alertas/cancelado?status=ok"
    sub.refresh_from_db()
    assert not sub.is_active


@pytest.mark.django_db
def test_link_de_cancelamento_invalido_devolve_ao_site_sinalizando_erro(client, settings):
    settings.PUBLIC_SITE_URL = SITE_ORIGIN

    response = client.get("/api/v1/subscriptions/unsubscribe/token-que-nao-existe")

    assert response.status_code == 302
    assert response["Location"] == f"{SITE_ORIGIN}/alertas/cancelado?status=invalido"


def _post(client, **overrides):
    payload = {
        "email": "leitora@example.com",
        "accepted_terms": True,
        "alerts": [{"frequency": "weekly", "ast": {"field": "tema", "op": "eq", "value": "saude"}}],
    }
    payload.update(overrides)
    return client.post(
        "/api/v1/subscriptions/",
        data=payload,
        content_type="application/json",
        HTTP_ORIGIN=SITE_ORIGIN,
    )


@pytest.mark.django_db
def test_assinar_as_duas_frequencias_cria_duas_inscricoes_e_um_email(client, outbox):
    response = _post(
        client,
        alerts=[
            {"frequency": "weekly", "ast": {"field": "tema", "op": "eq", "value": "saude"}},
            {
                "frequency": "daily",
                "ast": {
                    "op": "AND",
                    "children": [
                        {"field": "tema", "op": "eq", "value": "saude"},
                        {"field": "casa", "op": "eq", "value": "camara"},
                    ],
                },
            },
        ],
    )

    assert response.status_code == 201
    subs = Subscription.objects.filter(email="leitora@example.com")
    assert {s.frequency for s in subs} == {"weekly", "daily"}
    assert not any(s.is_active for s in subs)
    assert len(outbox) == 1
    assert outbox[0].to == ["leitora@example.com"]
    html = outbox[0].alternatives[0][0]
    assert "Confirmar inscrição" in html
    assert "/api/v1/assets/emails/header.png" in html
    assert f"/api/v1/subscriptions/confirm/{subs.first().confirm_token}" in html


@pytest.mark.django_db(transaction=True)
def test_so_inscricao_confirmada_recebe_alerta(client, outbox, settings, daily_clock):
    settings.PUBLIC_SITE_URL = SITE_ORIGIN
    _post(
        client,
        email="confirmacao@example.org",
        alerts=[{"frequency": "daily", "ast": {"field": "casa", "op": "eq", "value": "camara"}}],
    )
    subscription = Subscription.objects.get(email="confirmacao@example.org")

    before_confirmation = Proposition.objects.create(
        house="camara",
        external_id=910001,
        type_code="pl",
        number_label="PL 1/2026",
        number=1,
        year=2026,
        presented_at="2026-01-01",
        ementa="Proposição antes da confirmação.",
        current_status="Em tramitação",
        is_approved=True,
    )
    match_and_notify.delay(before_confirmation.pk)

    # O único e-mail é a confirmação enviada no cadastro; ainda não há alerta.
    assert len(outbox) == 1
    assert outbox[0].subject == "Confirme sua inscrição em nossos alertas"
    assert outbox[0].from_email == "Elas no Congresso <alertas@elasnocongresso.local>"

    response = client.get(f"/api/v1/subscriptions/confirm/{subscription.confirm_token}")
    assert response["Location"] == f"{SITE_ORIGIN}/?subscription=confirmado"

    after_confirmation = Proposition.objects.create(
        house="camara",
        external_id=910002,
        type_code="pl",
        number_label="PL 2/2026",
        number=2,
        year=2026,
        presented_at="2026-01-02",
        ementa="Proposição após a confirmação.",
        current_status="Em tramitação",
        is_approved=True,
    )
    match_and_notify.delay(after_confirmation.pk)

    assert len(outbox) == 1
    daily_clock.now = daily_clock.now.replace(hour=9)
    send_daily_digest()
    assert len(outbox) == 2
    assert outbox[1].to == ["confirmacao@example.org"]
    assert outbox[1].subject == "[Elas no Congresso] Resumo do dia: 1 proposição"
    assert after_confirmation.number_label in outbox[1].body
    assert before_confirmation.number_label not in outbox[1].body


@pytest.mark.django_db
def test_um_clique_confirma_todas_as_frequencias_do_mesmo_email(client, outbox, settings):
    settings.PUBLIC_SITE_URL = SITE_ORIGIN
    _post(
        client,
        alerts=[
            {"frequency": "weekly", "ast": {"field": "tema", "op": "eq", "value": "saude"}},
            {"frequency": "daily", "ast": {"field": "casa", "op": "eq", "value": "camara"}},
        ],
    )
    token = Subscription.objects.filter(email="leitora@example.com").first().confirm_token

    client.get(f"/api/v1/subscriptions/confirm/{token}")

    subs = Subscription.objects.filter(email="leitora@example.com")
    assert all(s.is_active and s.confirmed_at for s in subs)


@pytest.mark.django_db
def test_reinscrever_substitui_as_preferencias_anteriores(client, outbox):
    _post(
        client,
        alerts=[{"frequency": "weekly", "ast": {"field": "tema", "op": "eq", "value": "saude"}}],
    )

    _post(
        client,
        alerts=[{"frequency": "daily", "ast": {"field": "tema", "op": "eq", "value": "educacao"}}],
    )

    subs = list(Subscription.objects.filter(email="leitora@example.com"))
    assert len(subs) == 1
    assert subs[0].frequency == "daily"
    assert subs[0].ast["value"] == "educacao"


@pytest.mark.django_db
def test_cancelar_encerra_todas_as_frequencias_do_email(client, outbox, settings):
    settings.PUBLIC_SITE_URL = SITE_ORIGIN
    _post(
        client,
        alerts=[
            {"frequency": "weekly", "ast": {"field": "tema", "op": "eq", "value": "saude"}},
            {"frequency": "daily", "ast": {"field": "casa", "op": "eq", "value": "camara"}},
        ],
    )
    first = Subscription.objects.filter(email="leitora@example.com").first()
    client.get(f"/api/v1/subscriptions/confirm/{first.confirm_token}")

    client.get(f"/api/v1/subscriptions/unsubscribe/{first.unsubscribe_token}")

    assert not Subscription.objects.filter(email="leitora@example.com", is_active=True).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "ast",
    [
        {"field": "tema", "op": "explodir", "value": "saude"},
        {"field": "ano", "op": "eq", "value": "não é número"},
        {"op": "AND", "children": [{"field": "tema", "op": "cont", "value": "x"}]},
        {},
        {"op": "AND", "children": []},
        {"field": "ementa", "op": "contains", "value": "mulher"},
        {"field": "celeridade", "op": "eq", "value": 1},
        {"field": "categoria", "op": "in", "value": []},
        {"field": "casa", "op": "gte", "value": "camara"},
    ],
    ids=[
        "operador-desconhecido",
        "numero-invalido",
        "operador-ruim-aninhado",
        "vazio",
        "and-sem-filhos",
        "campo-desconhecido",
        "celeridade-sem-documento",
        "in-vazio",
        "faixa-em-campo-textual",
    ],
)
def test_ast_malformado_e_recusado_sem_500(client, outbox, ast):
    response = _post(client, alerts=[{"frequency": "weekly", "ast": ast}])

    assert response.status_code == 422
    assert not Subscription.objects.exists()
    assert outbox == []


@pytest.mark.django_db
def test_rajada_do_mesmo_ip_e_barrada(client, outbox, settings):
    limite = settings.SUBSCRIPTION_THROTTLE_RATE_PER_HOUR

    ok = [_post(client, email=f"pessoa{i}@example.com").status_code for i in range(limite)]
    excedente = _post(client, email="excedente@example.com")

    assert ok == [201] * limite
    assert excedente.status_code == 429
    assert not Subscription.objects.filter(email="excedente@example.com").exists()


@pytest.mark.django_db
def test_sem_aceite_dos_termos_nao_inscreve(client, outbox):
    response = _post(client, accepted_terms=False)

    assert response.status_code == 422
    assert not Subscription.objects.exists()
    assert outbox == []


@pytest.mark.django_db
def test_aceite_dos_termos_fica_registrado(client, outbox):
    _post(client)

    sub = Subscription.objects.get(email="leitora@example.com")
    assert sub.accepted_terms_at is not None


@pytest.mark.django_db
def test_frequencia_desconhecida_e_recusada(client, outbox):
    response = _post(
        client,
        alerts=[{"frequency": "mensal", "ast": {"field": "tema", "op": "eq", "value": "saude"}}],
    )

    assert response.status_code == 422
    assert not Subscription.objects.exists()


@pytest.mark.django_db
def test_conectivo_em_minusculas_e_aceito(client, outbox):
    ast = {"op": "and", "children": [{"field": "casa", "op": "eq", "value": "camara"}]}

    response = _post(client, alerts=[{"frequency": "daily", "ast": ast}])

    assert response.status_code == 201


def _confirmar(client, email="leitora@example.com"):
    pendente = Subscription.objects.filter(email=email, confirmed_at__isnull=True).first()
    return client.get(f"/api/v1/subscriptions/confirm/{pendente.confirm_token}")


@pytest.mark.django_db
def test_link_antigo_de_confirmacao_nao_reativa_quem_cancelou(client, outbox, settings):
    settings.PUBLIC_SITE_URL = SITE_ORIGIN
    _post(client)
    sub = Subscription.objects.get(email="leitora@example.com")
    client.get(f"/api/v1/subscriptions/confirm/{sub.confirm_token}")
    client.get(f"/api/v1/subscriptions/unsubscribe/{sub.unsubscribe_token}")

    response = client.get(f"/api/v1/subscriptions/confirm/{sub.confirm_token}")

    assert response["Location"] == f"{SITE_ORIGIN}/?subscription=invalido"
    assert not Subscription.objects.filter(email="leitora@example.com", is_active=True).exists()


@pytest.mark.django_db
def test_link_de_confirmacao_expira_no_prazo(client, outbox, settings):
    from datetime import timedelta

    from django.utils import timezone

    settings.PUBLIC_SITE_URL = SITE_ORIGIN
    _post(client)
    vencido = timezone.now() - timedelta(hours=settings.SUBSCRIPTION_CONFIRM_TTL_HOURS + 1)
    Subscription.objects.update(created_at=vencido)

    response = _confirmar(client)

    assert response["Location"] == f"{SITE_ORIGIN}/?subscription=invalido"
    assert not Subscription.objects.filter(is_active=True).exists()


@pytest.mark.django_db
def test_reinscrever_mantem_alertas_ate_confirmar_e_preserva_historico(client, outbox):
    from django.utils import timezone

    from apps.subscriptions.models import AlertDelivery

    _post(client, alerts=[{"frequency": "daily", "ast": {"field": "casa", "op": "eq", "value": "camara"}}])
    _confirmar(client)
    antiga = Subscription.objects.get(email="leitora@example.com")
    prop = Proposition.objects.create(
        external_id=9101, house="camara", type_code="PL", number_label="PL 9101/2026",
        number=9101, year=2026, ementa="Ementa", is_approved=True,
        presented_at=timezone.localdate(),
    )
    AlertDelivery.objects.create(subscription=antiga, proposition=prop)

    _post(client, alerts=[{"frequency": "daily", "ast": {"field": "casa", "op": "eq", "value": "senado"}}])

    antiga.refresh_from_db()
    assert antiga.is_active

    _confirmar(client)

    nova = Subscription.objects.get(email="leitora@example.com")
    assert nova.pk != antiga.pk
    assert nova.is_active and nova.ast["value"] == "senado"
    assert AlertDelivery.objects.filter(subscription=nova, proposition=prop).exists()


@pytest.mark.django_db
def test_limpeza_remove_pendentes_mas_preserva_canceladas(client, outbox):
    from datetime import timedelta

    from django.utils import timezone

    from apps.subscriptions.tasks import cleanup_unconfirmed_subscriptions

    antigo = timezone.now() - timedelta(days=10)
    cancelada = _make_subscription(email="cancelou@example.com", confirmed_at=antigo)
    pendente = _make_subscription(email="nunca@example.com")
    Subscription.objects.update(created_at=antigo)

    cleanup_unconfirmed_subscriptions()

    assert Subscription.objects.filter(pk=cancelada.pk).exists()
    assert not Subscription.objects.filter(pk=pendente.pk).exists()
