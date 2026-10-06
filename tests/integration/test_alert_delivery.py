"""Daily delivery and compatibility with retired weekly tasks/subscriptions."""

import datetime

import pytest

from apps.legislatures.models import Parliamentarian
from apps.propositions.models import (
    AssessmentOrganization,
    Proposition,
    PropositionAnalysis,
    PropositionAnnotation,
    PropositionEvent,
    PropositionRapporteur,
)
from apps.subscriptions.models import AlertDelivery, DailyDigestDelivery, PendingAlert, Subscription
from apps.subscriptions.tasks import (
    match_and_notify,
    send_daily_digest,
    send_daily_digest_email,
    send_digest_email,
    send_weekly_digest,
)


def _make_annotation(proposition, **kwargs):
    org, _ = AssessmentOrganization.objects.get_or_create(name="Anis")
    return PropositionAnnotation.objects.create(proposition=proposition, organization=org, **kwargs)


def _make_parlamentar(**kwargs):
    defaults = {"full_name": "Maria Silva", "gender": "F"}
    defaults.update(kwargs)
    return Parliamentarian.objects.create(**defaults)


def _make_proposition(**kwargs):
    defaults = {
        "house": "camara",
        "external_id": 1,
        "type_code": "pl",
        "number_label": "PL 1/2024",
        "number": 1,
        "year": 2024,
        "presented_at": datetime.date(2024, 1, 1),
        "ementa": "Ementa de teste",
        "current_status": "Em tramitação",
        "is_approved": True,
    }
    defaults.update(kwargs)
    return Proposition.objects.create(**defaults)


def _make_subscription(**kwargs):
    defaults = {
        "email": "leitora@example.com",
        "ast": {},
        "query": "casa_camara",
        "frequency": "daily",
        "is_active": True,
    }
    defaults.update(kwargs)
    return Subscription.objects.create(**defaults)


# transaction=True: o disparo do alerta acontece no on_commit, que não roda
# quando o teste segura tudo numa transação revertida no fim.
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("daily_clock")
class TestAlertaDiario:
    def test_inscricao_diaria_espera_o_horario_do_resumo(self, outbox, daily_clock):
        _make_subscription(frequency="daily")

        prop = _make_proposition(external_id=200)  # o post_save já enfileira o match

        assert outbox == []
        daily_clock.now = daily_clock.now.replace(hour=9)
        send_daily_digest()
        assert [m.to for m in outbox] == [["leitora@example.com"]]
        html = outbox[0].alternatives[0][0]
        assert "Radar Urgente" in html
        assert prop.number_label in html
        assert "/api/v1/assets/emails/daily-header.png" in html

    def test_inscricao_semanal_nao_recebe_alerta_imediato(self, outbox):
        _make_subscription(frequency="weekly")

        _make_proposition(external_id=201)

        assert outbox == []

    def test_proposicao_pendente_nao_dispara_alerta_ate_ser_aprovada(self, outbox, daily_clock):
        _make_subscription(frequency="daily")
        prop = _make_proposition(external_id=202, is_approved=False)

        assert outbox == []

        prop.is_approved = True
        prop.save(update_fields=["is_approved"])

        assert outbox == []
        daily_clock.now = daily_clock.now.replace(hour=9)
        send_daily_digest()
        assert [message.to for message in outbox] == [["leitora@example.com"]]

    def test_filtro_por_proposicao_so_alerta_daquela(self, outbox, daily_clock):
        acompanhada = _make_proposition(external_id=210, number_label="PL 7/2024")
        outra = _make_proposition(external_id=211, number_label="PL 8/2024")
        _make_subscription(frequency="daily", query=f"proposicao_{acompanhada.pk}")

        match_and_notify.delay(outra.pk)
        assert outbox == []

        match_and_notify.delay(acompanhada.pk)
        assert outbox == []
        daily_clock.now = daily_clock.now.replace(hour=9)
        send_daily_digest()
        assert [m.to for m in outbox] == [["leitora@example.com"]]

    def test_alerta_aguarda_resumo_quando_a_anotacao_chega(self, outbox, daily_clock):
        """A categoria vem da avaliação humana, dias depois da coleta — se o
        alerta só olhasse o post_save da proposição, nunca casaria."""
        _make_subscription(frequency="daily", query="categoria_violencias_de_genero")
        prop = _make_proposition(external_id=240)
        assert outbox == []

        _make_annotation(prop, category="violencias_de_genero")

        assert outbox == []
        daily_clock.now = daily_clock.now.replace(hour=9)
        send_daily_digest()
        assert [m.to for m in outbox] == [["leitora@example.com"]]

    def test_mesma_proposicao_nao_avisa_duas_vezes(self, outbox, daily_clock):
        _make_subscription(frequency="daily", query="casa_camara")
        prop = _make_proposition(external_id=241)
        assert outbox == []
        daily_clock.now = daily_clock.now.replace(hour=9)
        send_daily_digest()
        assert len(outbox) == 1

        _make_annotation(prop, category="saude")
        match_and_notify.delay(prop.pk)
        daily_clock.now += datetime.timedelta(days=1)
        send_daily_digest()

        assert len(outbox) == 1

    def test_categoria_de_fora_da_inscricao_nao_alerta(self, outbox):
        """As leitoras escolhem "Categorias 2026", não as palavras-chave do raspador."""
        _make_subscription(frequency="daily", query="categoria_violencias_de_genero")

        _make_annotation(_make_proposition(external_id=231), category="saude")

        assert outbox == []

    def test_filtro_por_relator_alerta_quando_ele_relata(self, outbox, daily_clock):
        relator = _make_parlamentar()
        _make_subscription(frequency="daily", query=f"relator_{relator.pk}")

        prop = _make_proposition(external_id=220)
        PropositionRapporteur.objects.create(
            proposition=prop, parliamentarian=relator, designated_at=datetime.date(2024, 2, 1)
        )
        match_and_notify.delay(prop.pk)

        assert outbox == []
        daily_clock.now = daily_clock.now.replace(hour=9)
        send_daily_digest()
        assert [m.to for m in outbox] == [["leitora@example.com"]]


@pytest.mark.django_db(transaction=True)
class TestRetiredWeeklyDigest:
    def test_legacy_tasks_no_longer_send_email(self, outbox):
        sub = _make_subscription(frequency="weekly")
        prop = _make_proposition(external_id=300)
        assert send_weekly_digest.delay().get() is None
        assert send_digest_email.delay(sub.pk, [prop.pk]).get() is None
        assert outbox == []
        assert not AlertDelivery.objects.exists()

    def test_migration_disables_only_weekly_schedules(self):
        from importlib import import_module
        from types import SimpleNamespace

        from django.apps import apps
        from django.conf import settings
        from django.db import connection
        from django_celery_beat.models import IntervalSchedule, PeriodicTask, PeriodicTasks

        interval = IntervalSchedule.objects.create(every=1, period=IntervalSchedule.DAYS)
        tasks = [
            PeriodicTask.objects.create(name=name, task=task, interval=interval)
            for name, task in (
                ("custom-weekly-name", "apps.subscriptions.tasks.send_weekly_digest"),
                ("old-send", "apps.subscriptions.tasks.send_digest_email"),
                ("daily", "apps.subscriptions.tasks.send_daily_digest"),
            )
        ]
        migration = import_module("apps.subscriptions.migrations.0006_retire_weekly_digest")
        last_change = PeriodicTasks.last_change()
        migration.disable_weekly_schedules(apps, SimpleNamespace(connection=connection))
        for task in tasks:
            task.refresh_from_db()
        assert [task.enabled for task in tasks] == [False, False, True]
        assert PeriodicTasks.last_change() > last_change
        assert "weekly-digest" not in settings.CELERY_BEAT_SCHEDULE
        assert settings.CELERY_BEAT_SCHEDULE["daily-digest"]["task"] == tasks[2].task


@pytest.mark.django_db(transaction=True)
class TestDigestDiario:
    def test_worker_nao_antecipa_envio_e_preserva_pendencias(self, outbox, daily_clock):
        sub = _make_subscription()
        _make_proposition(external_id=490)
        send_daily_digest_email(sub.email, "2026-10-06")
        assert outbox == []
        assert PendingAlert.objects.exists()
        assert not DailyDigestDelivery.objects.exists()

    def test_todos_os_usuarios_recebem_seus_matches_sem_inscricoes_semanais(
        self, outbox, daily_clock
    ):
        daily = _make_subscription()
        other = _make_subscription(email="other@example.com", query="casa_senado")
        _make_subscription(email="weekly@example.com", frequency="weekly")
        camara = _make_proposition(external_id=495)
        senado = _make_proposition(
            external_id=496, house="senado", number_label="PL 2/2024", number=2
        )
        daily_clock.now = daily_clock.now.replace(hour=9)
        send_daily_digest()
        assert {message.to[0] for message in outbox} == {daily.email, other.email}
        messages = {message.to[0]: message for message in outbox}
        assert camara.number_label in messages[daily.email].body
        assert senado.number_label not in messages[daily.email].body
        assert senado.number_label in messages[other.email].body
        assert camara.number_label not in messages[other.email].body

    def test_junta_proposicoes_e_inscricoes_do_mesmo_usuario(self, outbox, daily_clock):
        first = _make_subscription()
        second = _make_subscription(query="casa_camara")
        props = [_make_proposition(external_id=n, number_label=f"PL {n}/2026") for n in (500, 501)]
        assert PendingAlert.objects.count() == 4
        assert AlertDelivery.objects.count() == 0
        assert outbox == []

        send_daily_digest()
        assert outbox == []
        daily_clock.now = daily_clock.now.replace(hour=9)
        send_daily_digest()
        send_daily_digest()
        send_daily_digest_email(first.email, "2026-10-06")

        assert len(outbox) == 1
        assert "Resumo do dia: 2 proposições" in outbox[0].subject
        for prop in props:
            assert outbox[0].body.count(prop.number_label) == 1
        assert set(AlertDelivery.objects.values_list("subscription_id", flat=True)) == {
            first.pk,
            second.pk,
        }
        assert AlertDelivery.objects.count() == 4
        assert PendingAlert.objects.count() == 0
        assert DailyDigestDelivery.objects.filter(sent_at__isnull=False).count() == 1

    def test_matches_depois_das_nove_esperam_o_proximo_dia(self, outbox, daily_clock):
        _make_subscription()
        _make_proposition(external_id=510)
        daily_clock.now = daily_clock.now.replace(hour=9)
        send_daily_digest()
        daily_clock.now += datetime.timedelta(minutes=1)
        late = _make_proposition(external_id=511, number_label="PL 511/2026")
        send_daily_digest()
        assert len(outbox) == 1
        assert PendingAlert.objects.filter(proposition=late).exists()

        daily_clock.now += datetime.timedelta(days=1)
        send_daily_digest()
        assert len(outbox) == 2
        assert "PL 511/2026" in outbox[1].body
        assert PendingAlert.objects.count() == 0

    def test_horario_configuravel_e_corte_fixo_mesmo_com_atraso(
        self, outbox, daily_clock, settings
    ):
        settings.DAILY_DIGEST_TIME = datetime.time(10, 30)
        _make_subscription()
        early = _make_proposition(external_id=520)
        daily_clock.now = daily_clock.now.replace(hour=10, minute=29)
        send_daily_digest()
        assert outbox == []
        daily_clock.now = daily_clock.now.replace(hour=10, minute=31)
        late = _make_proposition(external_id=521, number_label="PL 521/2026")
        send_daily_digest()
        assert len(outbox) == 1
        assert early.number_label in outbox[0].body
        assert late.number_label not in outbox[0].body
        assert PendingAlert.objects.filter(proposition=late).exists()

    def test_nao_envia_resumo_vazio(self, outbox, daily_clock):
        _make_subscription()
        daily_clock.now = daily_clock.now.replace(hour=9)
        send_daily_digest()
        assert outbox == []
        assert not DailyDigestDelivery.objects.exists()

    @pytest.mark.parametrize("change", ["inactive", "weekly", "unapproved", "filter"])
    def test_revalida_pendencias_antes_do_envio(self, outbox, daily_clock, change):
        sub = _make_subscription()
        prop = _make_proposition(external_id=530)
        assert PendingAlert.objects.exists()
        if change == "unapproved":
            Proposition.objects.filter(pk=prop.pk).update(is_approved=False)
        else:
            changes = {
                "inactive": {"is_active": False},
                "weekly": {"frequency": "weekly"},
                "filter": {"query": "casa_senado"},
            }
            Subscription.objects.filter(pk=sub.pk).update(**changes[change])
        daily_clock.now = daily_clock.now.replace(hour=9)
        send_daily_digest_email(sub.email, "2026-10-06")
        assert outbox == []
        assert not AlertDelivery.objects.exists()
        assert not DailyDigestDelivery.objects.filter(sent_at__isnull=False).exists()

    def test_falha_no_envio_preserva_pendencias_para_retry(self, outbox, daily_clock):
        from unittest.mock import patch

        from anymail.exceptions import AnymailError

        sub = _make_subscription()
        prop = _make_proposition(external_id=540)
        daily_clock.now = daily_clock.now.replace(hour=9)
        with (
            patch("apps.subscriptions.tasks._send", side_effect=AnymailError("SES unavailable")),
            pytest.raises(AnymailError),
        ):
            # Call the task body so Celery's eager autoretry cannot hide the first failure.
            send_daily_digest_email._orig_run(sub.email, "2026-10-06")
        assert PendingAlert.objects.filter(subscription=sub, proposition=prop).exists()
        assert not AlertDelivery.objects.exists()
        assert not DailyDigestDelivery.objects.exists()

        send_daily_digest()
        assert len(outbox) == 1
        assert AlertDelivery.objects.filter(subscription=sub, proposition=prop).exists()

    def test_tarefa_atrasada_nao_envia_fora_da_data(self, outbox, daily_clock):
        sub = _make_subscription()
        _make_proposition(external_id=550)
        daily_clock.now += datetime.timedelta(days=1)
        daily_clock.now = daily_clock.now.replace(hour=9)
        send_daily_digest_email(sub.email, "2026-10-06")
        assert outbox == []
        assert PendingAlert.objects.exists()
        send_daily_digest()
        assert len(outbox) == 1

    def test_duas_tarefas_concorrentes_enviam_um_email(self, daily_clock):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from unittest.mock import patch

        from django.db import connections

        sub = _make_subscription()
        _make_proposition(external_id=560)
        daily_clock.now = daily_clock.now.replace(hour=9)
        barrier = Barrier(2)

        def run():
            try:
                barrier.wait(timeout=10)
                return send_daily_digest_email(sub.email, "2026-10-06")
            finally:
                connections.close_all()

        with (
            patch("apps.subscriptions.tasks._send", return_value="message-id") as send,
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            results = list(executor.map(lambda _: run(), range(2)))
        assert results == ["message-id", "message-id"]
        assert send.call_count == 1
        assert DailyDigestDelivery.objects.filter(sent_at__isnull=False).count() == 1
        assert PendingAlert.objects.count() == 0


@pytest.mark.django_db
class TestDailyLayout:
    @pytest.mark.parametrize("days, expected", [(180, "Travada"), (360, "Esquecida")])
    def test_grupos_de_inatividade_usam_o_calculo_existente(self, daily_clock, days, expected):
        from apps.subscriptions.email_templates import render_daily_digest

        sub = _make_subscription()
        prop = _make_proposition(
            external_id=590, presented_at=daily_clock.now.date() - datetime.timedelta(days=days)
        )
        PropositionEvent.objects.create(
            proposition=prop, event_at=daily_clock.now, is_countable=False
        )
        assert f"Celeridade: {expected}" in render_daily_digest(sub, [prop])

    def test_agrupa_por_tema_e_celeridade_em_html_e_texto(self, daily_clock):
        from apps.subscriptions.email_templates import render_daily_digest, render_daily_digest_text

        sub = _make_subscription()
        fast = _make_proposition(
            external_id=600, number_label="PL 600/2026", presented_at=datetime.date(2026, 10, 5)
        )
        slow = _make_proposition(
            external_id=601, number_label="PL 601/2026", presented_at=datetime.date(2026, 6, 1)
        )
        health = _make_proposition(
            external_id=602, number_label="PL 602/2026", presented_at=datetime.date(2026, 10, 5)
        )
        for prop in (fast, slow):
            _make_annotation(prop, category="violencias_de_genero")
        _make_annotation(health, category="saude")
        for day in (1, 2, 3):
            PropositionEvent.objects.create(
                proposition=fast, event_at=daily_clock.now.replace(day=day), is_countable=True
            )

        html = render_daily_digest(sub, [health, slow, fast, fast])
        text = render_daily_digest_text(sub, [health, slow, fast, fast])
        for body in (html, text):
            assert body.index("Violências de Gênero") < body.index("Celeridade: Tá voando")
            assert body.index("Celeridade: Tá voando") < body.index("PL 600/2026")
            assert body.index("PL 600/2026") < body.index("Celeridade: Lenta")
            assert body.index("Celeridade: Lenta") < body.index("PL 601/2026")
            assert (
                body.index("PL 601/2026") < body.index("Saúde") < body.index("Celeridade: Rápida")
            )
            assert body.count("PL 600/2026") == 1
            assert "Radar do dia" in body
        assert "/api/v1/assets/emails/daily-header.png" in html
        assert "weekly-header.png" not in html
        assert "Cancelar inscrição:" in text
        assert "Descadastrar-se" in html

    def test_tema_humano_prevalece_sobre_ia_e_multiplos_temas_nao_duplicam(self):
        from apps.subscriptions.email_templates import render_daily_digest

        sub = _make_subscription()
        prop = _make_proposition(external_id=610)
        PropositionAnalysis.objects.create(
            proposition=prop, theme_category="educacao_cultura", analysis_status="succeeded"
        )
        for category in ("saude", "saude", "direitos_sexuais_reprodutivos"):
            _make_annotation(prop, category=category)
        html = render_daily_digest(sub, [prop])
        assert "Saúde" in html
        assert "Direitos Sexuais e Reprodutivos" in html
        assert "Educação e Cultura" not in html
        assert html.count(f"<strong>{prop.number_label}</strong>") == 2  # uma vez por tema distinto

    @pytest.mark.parametrize(
        "status, expected", [("succeeded", "Saúde"), ("failed", "Sem tema informado")]
    )
    def test_fallback_de_tema_com_e_sem_analise_concluida(self, status, expected):
        from apps.subscriptions.email_templates import render_daily_digest

        sub = _make_subscription()
        prop = _make_proposition(external_id=620)
        PropositionAnalysis.objects.create(
            proposition=prop, theme_category="saude", analysis_status=status
        )
        assert expected in render_daily_digest(sub, [prop])

    def test_escapa_conteudo_e_preserva_metadados_e_links(self):
        from apps.subscriptions.email_templates import render_daily_digest, render_daily_digest_text

        sub = _make_subscription()
        prop = _make_proposition(
            external_id=630,
            ementa='<script>alert("ementa")</script>',
            tramitation_url="https://camara.example.test/proposicao?id=630&origem=email",
            regime="Urgência",
            enacted_law_type="Lei",
            enacted_law_number=1000,
            enacted_law_year=2026,
        )
        relator = _make_parlamentar()
        PropositionRapporteur.objects.create(
            proposition=prop, parliamentarian=relator, designated_at=datetime.date(2026, 10, 1)
        )
        html = render_daily_digest(sub, [prop])
        text = render_daily_digest_text(sub, [prop])
        assert '<script>alert("ementa")</script>' not in html
        assert "&lt;script&gt;" in html
        assert 'href="https://camara.example.test/proposicao?id=630&amp;origem=email"' in html
        for body in (html, text):
            assert "Relatoria: Maria Silva" in body
            assert "Regime de tramitação: Urgência" in body
            assert "Agora é Lei 1000/2026" in body


@pytest.mark.parametrize("configured, expected", [(None, "[9] [0]"), ("10:30", "[10] [30]")])
def test_beat_usa_horario_configurado_no_ambiente(configured, expected):
    import os
    import subprocess
    import sys

    env = os.environ.copy()
    env.pop("DAILY_DIGEST_TIME", None)
    if configured:
        env["DAILY_DIGEST_TIME"] = configured
    code = (
        "from config.settings.base import CELERY_BEAT_SCHEDULE, CELERY_TIMEZONE; "
        "entry = CELERY_BEAT_SCHEDULE['daily-digest']; "
        "assert entry['task'] == 'apps.subscriptions.tasks.send_daily_digest'; "
        "print(sorted(entry['schedule'].hour), sorted(entry['schedule'].minute)); "
        "print(CELERY_TIMEZONE); "
        "assert len(entry['schedule'].day_of_week) == 7"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
    )
    assert result.stdout.splitlines() == [expected, "America/Sao_Paulo"]
