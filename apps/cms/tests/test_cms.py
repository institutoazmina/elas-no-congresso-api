import io
from unittest.mock import Mock

import httpx
import pytest
from botocore.exceptions import ClientError
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from PIL import Image

from apps.cms import deploy, storage, tasks
from apps.cms.admin import AboutPartnerForm
from apps.cms.images import ImageSpec, normalize
from apps.cms.models import (
    AboutCopy,
    AboutPage,
    AboutPartner,
    AboutTimelineEvent,
    ActivityPage,
    AlertsPage,
    FeministAICategory,
    FeministAIEvaluationMetric,
    FeministAIPage,
    FooterAlertsPage,
    HomeCopy,
    HomePage,
    ReportsPage,
)

pytestmark = pytest.mark.django_db

SPEC = ImageSpec(1080, 1350)


def image_file(width=1080, height=1350, fmt="PNG", name="ilustracao.png"):
    buffer = io.BytesIO()
    Image.new("RGBA" if fmt != "JPEG" else "RGB", (width, height), (66, 66, 246, 255)).save(
        buffer, fmt
    )
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=f"image/{fmt.lower()}")


@pytest.fixture
def bucket(settings, monkeypatch):
    settings.CMS_S3_BUCKET = "elas-no-congresso-site"
    settings.CMS_PUBLIC_BASE_URL = "https://www.elasnocongresso.com.br/"
    settings.CMS_CLOUDFRONT_DISTRIBUTION_ID = "E123"
    s3, cloudfront = Mock(), Mock()
    monkeypatch.setattr(storage, "_client", lambda: s3)
    monkeypatch.setattr(storage, "_cloudfront", lambda: cloudfront)
    s3.cloudfront = cloudfront
    return s3


def invalidated_paths(cloudfront):
    return [
        call.kwargs["InvalidationBatch"]["Paths"]["Items"]
        for call in cloudfront.create_invalidation.call_args_list
    ]


@pytest.fixture
def admin_client():
    user = get_user_model().objects.create_superuser("editora", "editora@example.com", "senha")
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def deploy_task(settings, monkeypatch):
    settings.SITE_DEPLOY_GITHUB_TOKEN = "token"
    settings.SITE_DEPLOY_DELAY_SECONDS = 30
    tasks.cache.delete(tasks.PENDING_KEY)
    fake = Mock()
    monkeypatch.setattr(tasks.request_site_deploy, "apply_async", fake)
    return fake


PAGES = [
    (
        "/api/v1/cms/alerts",
        AlertsPage,
        "Alertas",
        "Acompanhe as movimentações do Legislativo no Radar do Congresso",
        "alertas",
    ),
    (
        "/api/v1/cms/reports",
        ReportsPage,
        "Reportagens",
        "Veja as histórias que os dados do Congresso nos contam.",
        "reportagens",
    ),
    (
        "/api/v1/cms/activity",
        ActivityPage,
        "Atividade Legislativa",
        "Use filtros e explore as movimentações do Legislativo sensíveis a gênero, "
        "atualizadas diariamente pela nossa robô que monitora o Congresso.",
        "atividade-legislativa",
    ),
]


class TestEndpoint:
    @pytest.mark.parametrize(("path", "model", "title", "subtitle", "folder"), PAGES)
    def test_sem_registro_devolve_padroes_sem_gravar(self, path, model, title, subtitle, folder):
        response = Client().get(path)

        assert response["Cache-Control"] == "no-store"
        assert response.json() == {
            "title": title,
            "subtitle": subtitle,
            "hero_image": {
                "url": f"/media/cms/{folder}/hero.webp?v=0",
                "width": 1080,
                "height": 1350,
            },
        }
        assert not model.objects.exists()

    def test_imagem_usa_dominio_do_site_com_versao(self, bucket):
        page = AlertsPage.load()
        page.title = "Radar"
        page.save()

        body = Client().get("/api/v1/cms/alerts").json()

        assert body["title"] == "Radar"
        assert body["hero_image"] == {
            "url": "https://www.elasnocongresso.com.br/cms/alertas/hero.webp"
            f"?v={int(page.updated_at.timestamp())}",
            "width": 1080,
            "height": 1350,
        }


class TestNormalize:
    def test_regrava_em_webp_no_tamanho_exato(self):
        result = normalize(image_file(2160, 2700), SPEC, stem="hero")

        assert result.name == "hero.webp"
        image = Image.open(result)
        assert (image.format, image.size) == ("WEBP", (1080, 1350))

    def test_aceita_proporcao_quase_igual(self):
        image = Image.open(normalize(image_file(1100, 1350), SPEC, stem="hero"))
        assert image.size == (1080, 1350)

    @pytest.mark.parametrize(
        ("upload", "message"),
        [
            (image_file(1080, 1080), "mesma proporção"),
            (image_file(540, 675), "pelo menos"),
            (image_file(fmt="GIF", name="a.gif"), "PNG, JPEG ou WebP"),
            (SimpleUploadedFile("a.png", b"nao e imagem"), "Não foi possível ler"),
        ],
    )
    def test_recusa(self, upload, message):
        with pytest.raises(ValidationError, match=message):
            normalize(upload, SPEC, stem="hero")


class TestAdmin:
    @pytest.fixture(autouse=True)
    def page(self):
        return AlertsPage.load()

    def change_url(self):
        return reverse("admin:cms_alertspage_change", args=[AlertsPage.SINGLETON_PK])

    @pytest.mark.parametrize("model", [AlertsPage, ReportsPage, ActivityPage, FeministAIPage])
    def test_menu_abre_o_registro_unico(self, admin_client, model):
        name = model._meta.model_name
        response = admin_client.get(reverse(f"admin:cms_{name}_changelist"))

        assert response.status_code == 302
        assert response["Location"] == reverse(f"admin:cms_{name}_change", args=[1])
        assert model.objects.count() == 1

    def test_reportagens_usa_a_propria_pasta(self, admin_client, bucket):
        ReportsPage.load()
        response = admin_client.post(
            reverse("admin:cms_reportspage_change", args=[1]),
            {"title": "Reportagens", "subtitle": "x", "hero_image": image_file()},
        )

        assert response.status_code == 302
        assert bucket.put_object.call_args.kwargs["Key"] == "cms/reportagens/hero.webp"

    def test_nao_permite_criar_nem_excluir(self, admin_client):
        assert admin_client.get(reverse("admin:cms_alertspage_add")).status_code == 403
        delete = reverse("admin:cms_alertspage_delete", args=[AlertsPage.SINGLETON_PK])
        assert admin_client.get(delete).status_code == 403

    def test_upload_sobrescreve_o_arquivo_e_invalida_o_cache(self, admin_client, bucket):
        for subtitle in ["Primeira", "Segunda"]:
            response = admin_client.post(
                self.change_url(),
                {"title": "Radar", "subtitle": subtitle, "hero_image": image_file()},
            )
            assert response.status_code == 302

        page = AlertsPage.objects.get()
        assert page.hero_image.name == "cms/alertas/hero.webp"
        assert (page.hero_image_width, page.hero_image_height) == (1080, 1350)
        keys = [call.kwargs["Key"] for call in bucket.put_object.call_args_list]
        assert keys == ["cms/alertas/hero.webp", "cms/alertas/hero.webp"]
        put = bucket.put_object.call_args.kwargs
        assert put["Bucket"] == "elas-no-congresso-site"
        assert put["ContentType"] == "image/webp"
        assert put["CacheControl"] == "public, max-age=3600, must-revalidate"
        assert invalidated_paths(bucket.cloudfront) == [["/cms/alertas/hero.webp*"]] * 2
        assert bucket.cloudfront.create_invalidation.call_args.kwargs["DistributionId"] == "E123"

    def test_imagem_so_pode_ser_substituida(self, admin_client, bucket):
        form = admin_client.get(self.change_url()).content.decode()
        assert "hero_image-clear" not in form

        response = admin_client.post(
            self.change_url(), {"title": "Radar", "subtitle": "x", "hero_image-clear": "on"}
        )

        assert response.status_code == 302
        page = AlertsPage.objects.get()
        assert (page.title, page.hero_image.name) == ("Radar", "cms/alertas/hero.webp")
        bucket.put_object.assert_not_called()

    def test_sem_bucket_sobrescreve_no_media_root(self, admin_client, settings, tmp_path):
        settings.MEDIA_ROOT = tmp_path
        for _ in range(2):
            admin_client.post(
                self.change_url(), {"title": "Radar", "subtitle": "x", "hero_image": image_file()}
            )

        assert [p.name for p in (tmp_path / "cms" / "alertas").iterdir()] == ["hero.webp"]

    def test_alertas_aceita_imagem_em_qualquer_resolucao(self, admin_client, bucket):
        response = admin_client.post(
            self.change_url(),
            {"title": "Alertas", "subtitle": "x", "hero_image": image_file(320, 180)},
        )

        assert response.status_code == 302
        page = AlertsPage.objects.get()
        assert (page.hero_image_width, page.hero_image_height) == (320, 180)
        assert bucket.put_object.call_args.kwargs["Key"] == "cms/alertas/hero.webp"

    def test_titulo_acima_do_limite_nao_salva(self, admin_client):
        response = admin_client.post(
            self.change_url(), {"title": "Alertas diários do Congresso", "subtitle": "x"}
        )

        assert response.status_code == 200
        assert AlertsPage.objects.get().title == "Alertas"


class TestPublishDefaults:
    def test_publica_o_original_uma_vez_no_media_root(self, settings, tmp_path):
        settings.MEDIA_ROOT = tmp_path
        published = tmp_path / "cms" / "alertas" / "hero.webp"

        call_command("cms_publish_defaults", stdout=io.StringIO())
        for folder in ["alertas", "reportagens", "atividade-legislativa", "sobre"]:
            image = Image.open(tmp_path / "cms" / folder / "hero.webp")
            assert (image.format, image.size) == ("WEBP", (1080, 1350))
        for name, size in [
            ("hero", (743, 1349)),
            ("flow-desktop", (820, 574)),
            ("flow-mobile", (524, 574)),
        ]:
            image = Image.open(tmp_path / "cms" / "ia-feminista" / f"{name}.webp")
            assert (image.format, image.size) == ("WEBP", size)
        for name, size in [
            ("hero", (513, 389)),
            ("explore", (1440, 1080)),
            ("quiteria", (1920, 1080)),
        ]:
            image = Image.open(tmp_path / "cms" / "home" / f"{name}.webp")
            assert (image.format, image.size) == ("WEBP", size)

        published.write_bytes(b"substituida no admin")
        out = io.StringIO()
        call_command("cms_publish_defaults", stdout=out)
        assert "já publicado" in out.getvalue()
        assert published.read_bytes() == b"substituida no admin"

    def test_no_bucket_so_envia_o_que_falta(self, bucket):
        bucket.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")

        call_command("cms_publish_defaults", stdout=io.StringIO())

        keys = [call.kwargs["Key"] for call in bucket.put_object.call_args_list]
        assert keys == [
            "cms/alertas/hero.webp",
            "cms/reportagens/hero.webp",
            "cms/atividade-legislativa/hero.webp",
            "cms/ia-feminista/hero.webp",
            "cms/ia-feminista/flow-desktop.webp",
            "cms/ia-feminista/flow-mobile.webp",
            "cms/sobre/hero.webp",
            "cms/home/hero.webp",
            "cms/home/explore.webp",
            "cms/home/quiteria.webp",
        ]
        assert invalidated_paths(bucket.cloudfront) == [[f"/{key}*"] for key in keys]

    def test_no_bucket_nao_sobrescreve_substituicao(self, bucket):
        call_command("cms_publish_defaults", stdout=io.StringIO())

        bucket.put_object.assert_not_called()

    def test_force_regrava(self, bucket):
        call_command("cms_publish_defaults", "--force", stdout=io.StringIO())

        bucket.head_object.assert_not_called()
        assert bucket.put_object.call_count == 10


class TestFeministAIPage:
    def test_migracao_inicializa_pagina_publicada_e_tabelas(self):
        page = FeministAIPage.objects.get(pk=1)

        assert page.hero_title_emphasis == "Maria Quitéria?"
        assert page.architecture_card_1_highlight == "87% de acurácia"
        assert FeministAICategory.objects.filter(page=page).count() == 10
        assert FeministAIEvaluationMetric.objects.filter(page=page).count() == 8

    def test_api_devolve_todo_o_conteudo_em_ordem(self):
        response = Client().get("/api/v1/cms/feminist-ai")

        assert response.status_code == 200
        assert response["Cache-Control"] == "no-store"
        data = response.json()
        assert data["content"]["feminism_paragraph_3_highlight"] == (
            "Atualmente estamos no segundo ciclo."
        )
        assert data["images"]["hero"]["width"] == 743
        assert data["images"]["flow_desktop"]["height"] == 574
        assert data["images"]["flow_mobile"]["url"].startswith(
            "/media/cms/ia-feminista/flow-mobile.webp?v="
        )
        assert data["categories"][0]["name"] == "Violências de Gênero"
        assert len(data["categories"]) == 10
        assert len(data["limitations"]) == 6
        assert len(data["evaluation_metrics"]) == 8
        assert len(data["evaluation_partitions"]) == 3
        assert len(data["thematic_metrics"]) == 14
        assert len(data["thematic_partitions"]) == 11
        assert len(data["open_links"]) == 3

    def test_admin_permite_editar_texto_e_linhas_sem_html_ou_json(self, admin_client):
        url = reverse("admin:cms_feministaipage_change", args=[1])
        response = admin_client.get(url)
        assert response.status_code == 200
        assert "Feminismo de dados" in response.content.decode()
        assert "Categorias temáticas" in response.content.decode()

        page = FeministAIPage.objects.get(pk=1)
        data = {
            field.name: getattr(page, field.name)
            for field in page._meta.fields
            if field.editable
            and field.name
            not in {"id", "updated_at", "hero_image", "flow_desktop_image", "flow_mobile_image"}
        }
        data["hero_title_emphasis"] = "QuitérIA?"
        for relation in [
            "feministaicategory_set",
            "feministailimitation_set",
            "feministaievaluationmetric_set",
            "feministaievaluationpartition_set",
            "feministaithematicmetric_set",
            "feministaithematicpartition_set",
            "feministaiopenlink_set",
        ]:
            objects = list(getattr(page, relation).all())
            data[f"{relation}-TOTAL_FORMS"] = len(objects)
            data[f"{relation}-INITIAL_FORMS"] = len(objects)
            data[f"{relation}-MIN_NUM_FORMS"] = 0
            data[f"{relation}-MAX_NUM_FORMS"] = 1000
            for index, obj in enumerate(objects):
                data[f"{relation}-{index}-id"] = obj.pk
                data[f"{relation}-{index}-page"] = page.pk
                for field in obj._meta.fields:
                    if field.name not in {"id", "page"}:
                        data[f"{relation}-{index}-{field.name}"] = getattr(obj, field.name)
        data["feministaicategory_set-0-concept"] = "Novo conceito editorial."
        data["feministaievaluationmetric_set-0-current"] = "0,90"

        response = admin_client.post(url, data)

        assert response.status_code == 302, response.content.decode()[:1000]
        body = Client().get("/api/v1/cms/feminist-ai").json()
        assert body["content"]["hero_title_emphasis"] == "QuitérIA?"
        assert body["categories"][0]["concept"] == "Novo conceito editorial."
        assert body["evaluation_metrics"][0]["current"] == "0,90"


class TestAboutPage:
    def test_conteudo_publicado_e_timeline_migrados(self):
        page = AboutPage.objects.get(pk=1)
        assert page.seo_title == "Sobre o Elas no Congresso | AzMina"
        assert page.copy.count() == 171
        assert page.timeline.count() == 5
        assert page.challenges.count() == 5
        assert page.partners.count() == 25

        response = Client().get("/api/v1/cms/about")
        assert response.status_code == 200
        assert response["Cache-Control"] == "no-store"
        data = response.json()
        assert data["content"]["seo_title"] == page.seo_title
        assert data["hero_image"]["url"].startswith("/media/cms/sobre/hero.webp?v=")
        assert data["timeline"][0]["tag"] == "Nasce o projeto"
        assert data["timeline"][2]["link_text"] == "Ruralômetro"
        assert data["partners"][0]["name"] == "Anis Bioética"

    def test_marcos_livres_e_textos_editados_chegam_ao_site(self, admin_client):
        page = AboutPage.objects.get(pk=1)
        assert admin_client.get(reverse("admin:cms_aboutpage_change", args=[1])).status_code == 200
        copy = AboutCopy.objects.get(key="s01_007")
        assert (
            admin_client.get(reverse("admin:cms_aboutcopy_change", args=[copy.pk])).status_code
            == 200
        )
        copy.value = "Nossa trajetória"
        copy.save()
        page.timeline.all().delete()
        AboutTimelineEvent.objects.create(
            page=page,
            position=2,
            date_prefix="Ano de",
            year="2027",
            description_before_link="Novo marco.",
            tag="Novo passo",
        )
        AboutTimelineEvent.objects.create(
            page=page,
            position=1,
            date_prefix="Ano de",
            year="2026",
            description_before_link="Marco anterior.",
            tag="Antes",
        )
        data = Client().get("/api/v1/cms/about").json()
        assert data["content"]["s01_007"] == "Nossa trajetória"
        assert [item["tag"] for item in data["timeline"]] == ["Antes", "Novo passo"]

    def test_logo_novo_precisa_de_arquivo(self):
        partner = AboutPartner(page=AboutPage.objects.get(pk=1), position=26, name="Nova rede")
        with pytest.raises(ValidationError):
            partner.full_clean()

    def test_parceiro_novo_envia_logo_sem_exigir_proporcao_fixa(self, settings, tmp_path):
        settings.MEDIA_ROOT = tmp_path
        page = AboutPage.objects.get(pk=1)
        form = AboutPartnerForm(
            data={"page": page.pk, "position": 26, "name": "Nova rede"},
            files={"logo_image": image_file(300, 100, name="rede.png")},
        )
        assert form.is_valid(), form.errors
        partner = form.save()
        assert partner.logo_image.name.startswith("cms/sobre/partners/")
        with Image.open(tmp_path / partner.logo_image.name) as logo:
            assert (logo.format, logo.size) == ("WEBP", (300, 100))
        original_path = partner.logo_image.name
        replacement = AboutPartnerForm(
            data={"page": page.pk, "position": 26, "name": "Nova rede"},
            files={"logo_image": image_file(400, 200, name="novo.png")},
            instance=partner,
        )
        assert replacement.is_valid(), replacement.errors
        replacement.save()
        assert partner.logo_image.name == original_path


class TestDeploy:
    def test_editar_trecho_de_sobre_agenda_deploy(
        self, deploy_task, django_capture_on_commit_callbacks
    ):
        copy = AboutCopy.objects.get(key="s01_007")
        copy.value = "Nossa trajetória"
        with django_capture_on_commit_callbacks(execute=True):
            copy.save()

        deploy_task.assert_called_once_with(countdown=30)

    def test_salvar_agenda_deploy_depois_do_commit(
        self, deploy_task, django_capture_on_commit_callbacks
    ):
        page = AlertsPage.load()
        page.title = "Radar"
        with django_capture_on_commit_callbacks(execute=True):
            page.save()

        deploy_task.assert_called_once_with(countdown=30)

    def test_rajada_de_salvamentos_vira_um_deploy(
        self, deploy_task, django_capture_on_commit_callbacks
    ):
        page = AlertsPage.load()
        with django_capture_on_commit_callbacks(execute=True):
            page.title = "Radar"
            page.save()
            page.subtitle = "Outro"
            page.save()

        deploy_task.assert_called_once()

    def test_sem_token_nao_dispara(self, settings, monkeypatch, django_capture_on_commit_callbacks):
        settings.SITE_DEPLOY_GITHUB_TOKEN = ""
        fake = Mock()
        monkeypatch.setattr(tasks.request_site_deploy, "apply_async", fake)

        with django_capture_on_commit_callbacks(execute=True):
            AlertsPage.load().save()

        fake.assert_not_called()

    def test_tarefa_chama_repository_dispatch(self, settings, monkeypatch):
        settings.SITE_DEPLOY_GITHUB_TOKEN = "token"
        settings.SITE_DEPLOY_GITHUB_REPOSITORY = "institutoazmina/elas-no-congresso"
        tasks.cache.set(tasks.PENDING_KEY, 1)
        post = Mock(return_value=httpx.Response(204, request=httpx.Request("POST", "https://x")))
        monkeypatch.setattr(deploy.httpx, "post", post)

        tasks.request_site_deploy.apply()

        url = post.call_args.args[0]
        assert url == "https://api.github.com/repos/institutoazmina/elas-no-congresso/dispatches"
        assert post.call_args.kwargs["json"] == {"event_type": "cms-content-updated"}
        assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer token"
        assert tasks.cache.get(tasks.PENDING_KEY) is None

    @pytest.mark.parametrize(
        ("status", "error"), [(502, deploy.RetryableDispatchError), (401, httpx.HTTPStatusError)]
    )
    def test_falhas_do_github(self, monkeypatch, status, error):
        response = httpx.Response(status, request=httpx.Request("POST", "https://x"))
        monkeypatch.setattr(deploy.httpx, "post", Mock(return_value=response))

        with pytest.raises(error):
            deploy.dispatch_site_deploy()


class TestHomePage:
    def test_admin_substitui_uma_imagem_sem_exigir_as_outras(self, admin_client, bucket):
        response = admin_client.post(
            reverse("admin:cms_homepage_change", args=[1]),
            {"hero_image": image_file(513, 389)},
        )

        assert response.status_code == 302
        assert HomePage.objects.get().hero_image.name == "cms/home/hero.webp"
        assert bucket.put_object.call_args.kwargs["Key"] == "cms/home/hero.webp"

    def test_migracao_e_api_preservam_conteudo_editorial_sem_dados_dos_graficos(self):
        assert HomePage.objects.filter(pk=1).exists()
        assert HomeCopy.objects.count() == 70

        response = Client().get("/api/v1/cms/home")

        assert response.status_code == 200
        assert response["Cache-Control"] == "no-store"
        data = response.json()
        assert data["content"]["hero_title_before_nas"] == "De olho "
        assert data["content"]["women_postit_before"].startswith("A cada 100")
        assert data["content"]["rights_postit_desktop_url"].startswith("https://azmina.com.br/")
        assert data["images"]["explore"]["width"] == 1440
        assert data["images"]["quiteria"]["height"] == 1080
        assert "charts" not in data and "news" not in data and "maps" not in data

    def test_trecho_editado_aparece_na_api_e_dispara_deploy(
        self, admin_client, deploy_task, django_capture_on_commit_callbacks
    ):
        copy = HomeCopy.objects.get(key="reports_title")
        with django_capture_on_commit_callbacks(execute=True):
            response = admin_client.post(
                reverse("admin:cms_homecopy_change", args=[copy.pk]),
                {"value": "Nossas reportagens", "_save": "Salvar"},
            )

        assert response.status_code == 302
        assert Client().get("/api/v1/cms/home").json()["content"]["reports_title"] == (
            "Nossas reportagens"
        )
        deploy_task.assert_called_once_with(countdown=30)

    def test_footer_global_e_editavel(self, admin_client):
        response = Client().get("/api/v1/cms/footer-alerts")
        assert response.json() == {
            "title": "Receba nossos alertas",
            "text": "Quer saber quando uma nova proposta sobre gênero é apresentada, "
            "ou quando algo de muita importância avança? A gente te avisa!",
            "cta_text": "Saiba mais",
            "cta_url": "/alertas",
        }
        assert response["Cache-Control"] == "no-store"
        assert FooterAlertsPage.objects.count() == 1

        response = admin_client.post(
            reverse("admin:cms_footeralertspage_change", args=[1]),
            {
                "title": "Acompanhe os alertas",
                "text": "Novidades do Congresso.",
                "cta_text": "Acessar",
                "cta_url": "/alertas",
            },
        )
        assert response.status_code == 302
        assert Client().get("/api/v1/cms/footer-alerts").json()["title"] == (
            "Acompanhe os alertas"
        )
