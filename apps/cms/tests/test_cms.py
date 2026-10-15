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
from apps.cms.images import ImageSpec, normalize
from apps.cms.models import AlertsPage

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


class TestEndpoint:
    def test_sem_registro_devolve_padroes_sem_gravar(self):
        response = Client().get("/api/v1/cms/alerts")

        assert response["Cache-Control"] == "no-store"
        assert response.json() == {
            "title": "Alertas",
            "subtitle": "Acompanhe as movimentações do Legislativo no Radar do Congresso",
            "hero_image": {
                "url": "/media/cms/alertas/hero.webp?v=0",
                "width": 1080,
                "height": 1350,
            },
        }
        assert not AlertsPage.objects.exists()

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

    def test_menu_abre_o_registro_unico(self, admin_client):
        response = admin_client.get(reverse("admin:cms_alertspage_changelist"))

        assert response.status_code == 302
        assert response["Location"] == self.change_url()
        assert AlertsPage.objects.count() == 1

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

    def test_imagem_fora_da_proporcao_nao_salva(self, admin_client, bucket):
        response = admin_client.post(
            self.change_url(),
            {"title": "Alertas", "subtitle": "x", "hero_image": image_file(1080, 1080)},
        )

        assert response.status_code == 200
        assert "mesma proporção" in response.content.decode()
        bucket.put_object.assert_not_called()

    def test_titulo_acima_do_limite_nao_salva(self, admin_client):
        response = admin_client.post(
            self.change_url(), {"title": "Alertas diários!", "subtitle": "x"}
        )

        assert response.status_code == 200
        assert AlertsPage.objects.get().title == "Alertas"


class TestPublishDefaults:
    def test_publica_o_original_uma_vez_no_media_root(self, settings, tmp_path):
        settings.MEDIA_ROOT = tmp_path
        published = tmp_path / "cms" / "alertas" / "hero.webp"

        call_command("cms_publish_defaults", stdout=io.StringIO())
        image = Image.open(published)
        assert (image.format, image.size) == ("WEBP", (1080, 1350))

        published.write_bytes(b"substituida no admin")
        out = io.StringIO()
        call_command("cms_publish_defaults", stdout=out)
        assert "já publicado" in out.getvalue()
        assert published.read_bytes() == b"substituida no admin"

    def test_no_bucket_so_envia_o_que_falta(self, bucket):
        bucket.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")

        call_command("cms_publish_defaults", stdout=io.StringIO())

        assert bucket.put_object.call_args.kwargs["Key"] == "cms/alertas/hero.webp"
        assert invalidated_paths(bucket.cloudfront) == [["/cms/alertas/hero.webp*"]]

    def test_no_bucket_nao_sobrescreve_substituicao(self, bucket):
        call_command("cms_publish_defaults", stdout=io.StringIO())

        bucket.put_object.assert_not_called()

    def test_force_regrava(self, bucket):
        call_command("cms_publish_defaults", "--force", stdout=io.StringIO())

        bucket.head_object.assert_not_called()
        assert bucket.put_object.call_args.kwargs["Key"] == "cms/alertas/hero.webp"


class TestDeploy:
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
