import io
from unittest.mock import Mock

import httpx
import pytest
from botocore.exceptions import ClientError
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db.models.deletion import ProtectedError
from django.test import Client
from django.urls import reverse
from PIL import Image
from unfold.widgets import UnfoldAdminTextareaWidget
from unfold_markdown.widgets import MarkdownWidget

from apps.cms import deploy, storage, tasks
from apps.cms.admin import (
    AboutPageForm,
    AboutPartnerForm,
    CmsMarkdownWidget,
    FeministAIMarkdownWidget,
    FeministAIPageForm,
    HomePageForm,
    MarkdownImageForm,
)
from apps.cms.images import ImageSpec, normalize
from apps.cms.models import (
    AboutCopy,
    AboutPage,
    AboutPartner,
    AboutTeamMember,
    ActivityPage,
    AlertsPage,
    FeministAICategory,
    FeministAIEvaluationMetric,
    FeministAIPage,
    FooterAlertsPage,
    HomeCopy,
    HomePage,
    MarkdownImage,
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
        "**Alertas**",
        "**Acompanhe as movimentações do Legislativo no Radar do Congresso**",
        "alertas",
        "Receba alertas sobre gênero no Congresso | Elas no Congresso",
        (
            "Receba alertas sobre projetos de lei e pautas de gênero que afetam os direitos "
            "de meninas, mulheres e pessoas LGBTQIAPN+ no Congresso Nacional."
        ),
    ),
    (
        "/api/v1/cms/reports",
        ReportsPage,
        "**Reportagens**",
        "**Veja as histórias que os dados do Congresso nos contam.**",
        "reportagens",
        "Reportagens: Congresso e política de gênero | AzMina",
        (
            "Leia reportagens da Revista AzMina sobre o Congresso Nacional, projetos de lei, "
            "política de gênero e direitos das mulheres e pessoas LGBTQIAPN+."
        ),
    ),
    (
        "/api/v1/cms/activity",
        ActivityPage,
        "**Atividade Legislativa**",
        "**Use filtros e explore as movimentações do Legislativo sensíveis a gênero, "
        "atualizadas diariamente pela nossa robô que monitora o Congresso.**",
        "atividade-legislativa",
        "Atividade Legislativa e pautas de gênero | Elas no Congresso",
        (
            "Explore dados sobre projetos de lei e pautas de gênero no Congresso Nacional em "
            "um dashboard interativo sobre atividade legislativa e direitos."
        ),
    ),
]


class TestEndpoint:
    @pytest.mark.parametrize(
        ("path", "model", "title", "subtitle", "folder", "seo_title", "seo_description"),
        PAGES,
    )
    def test_sem_registro_devolve_padroes_sem_gravar(
        self, path, model, title, subtitle, folder, seo_title, seo_description
    ):
        response = Client().get(path)

        assert response["Cache-Control"] == "no-store"
        assert response.json() == {
            "seo_title": seo_title,
            "seo_description": seo_description,
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

    @staticmethod
    def form_data(model=AlertsPage, **updates):
        page = model.load()
        data = {
            "seo_title": page.seo_title,
            "seo_description": page.seo_description,
            "title": page.title,
            "subtitle": page.subtitle,
        }
        return data | updates

    @pytest.mark.parametrize("model", [AlertsPage, ReportsPage, ActivityPage, FeministAIPage])
    def test_menu_abre_o_registro_unico(self, admin_client, model):
        name = model._meta.model_name
        response = admin_client.get(reverse(f"admin:cms_{name}_changelist"))

        assert response.status_code == 302
        assert response["Location"] == reverse(f"admin:cms_{name}_change", args=[1])
        assert model.objects.count() == 1

    @pytest.mark.parametrize(
        "model", [HomePage, ActivityPage, AlertsPage, FeministAIPage, ReportsPage, AboutPage]
    )
    def test_todas_as_paginas_exibem_secao_seo(self, model):
        model_admin = admin.site._registry[model]

        assert model_admin.fieldsets[0] == (
            "SEO",
            {"fields": ["seo_title", "seo_description"]},
        )
        assert {"seo_title", "seo_description"} <= set(model_admin.form.base_fields)

    @pytest.mark.parametrize(
        ("model", "title_field", "description_field"),
        [
            (HomePage, "hero_title", "hero_description"),
            (ActivityPage, "title", "subtitle"),
            (AlertsPage, "title", "subtitle"),
            (FeministAIPage, "hero_title", "hero_description"),
            (ReportsPage, "title", "subtitle"),
            (AboutPage, "hero_title", "hero_description"),
        ],
    )
    def test_instrucoes_do_topo_ficam_abaixo_dos_campos(
        self, model, title_field, description_field
    ):
        fields = admin.site._registry[model].form.base_fields
        title = fields[title_field]
        description = fields[description_field]

        assert title.label == "Título"
        assert description.label == "Descrição"
        assert fields["hero_image"].label == "Ilustração"
        for field in [title, description]:
            assert "**texto**" in field.help_text
            assert "quebra de linha" in field.help_text
            assert "**" not in field.label
            assert "~~" not in field.label

        if model is HomePage:
            assert "~~texto~~ para taxado" in description.help_text

    def test_reportagens_usa_a_propria_pasta(self, admin_client, bucket):
        ReportsPage.load()
        response = admin_client.post(
            reverse("admin:cms_reportspage_change", args=[1]),
            self.form_data(
                ReportsPage,
                title="Reportagens",
                subtitle="x",
                hero_image=image_file(),
            ),
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
                self.form_data(title="Radar", subtitle=subtitle, hero_image=image_file()),
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
            self.change_url(),
            self.form_data(title="Radar", subtitle="x", **{"hero_image-clear": "on"}),
        )

        assert response.status_code == 302
        page = AlertsPage.objects.get()
        assert (page.title, page.hero_image.name) == ("Radar", "cms/alertas/hero.webp")
        bucket.put_object.assert_not_called()

    def test_sem_bucket_sobrescreve_no_media_root(self, admin_client, settings, tmp_path):
        settings.MEDIA_ROOT = tmp_path
        for _ in range(2):
            admin_client.post(
                self.change_url(),
                self.form_data(title="Radar", subtitle="x", hero_image=image_file()),
            )

        assert [p.name for p in (tmp_path / "cms" / "alertas").iterdir()] == ["hero.webp"]

    def test_alertas_aceita_imagem_em_qualquer_resolucao(self, admin_client, bucket):
        response = admin_client.post(
            self.change_url(),
            self.form_data(title="Alertas", subtitle="x", hero_image=image_file(320, 180)),
        )

        assert response.status_code == 302
        page = AlertsPage.objects.get()
        assert (page.hero_image_width, page.hero_image_height) == (320, 180)
        assert bucket.put_object.call_args.kwargs["Key"] == "cms/alertas/hero.webp"

    @pytest.mark.parametrize(
        "model", [AlertsPage, ReportsPage, ActivityPage, FeministAIPage, AboutPage, HomePage]
    )
    def test_todos_os_headers_aceitam_qualquer_resolucao(self, model):
        form = admin.site._registry[model].form()

        assert form.image_specs()["hero_image"] == (None, "hero")

    def test_titulo_acima_do_limite_nao_salva(self, admin_client):
        response = admin_client.post(
            self.change_url(),
            self.form_data(title="Alertas diários do Congresso", subtitle="x"),
        )

        assert response.status_code == 200
        assert AlertsPage.objects.get().title == "**Alertas**"


class TestMarkdownImageGallery:
    def test_upload_normaliza_e_guarda_metadados(self, settings, tmp_path, admin_client):
        settings.MEDIA_ROOT = tmp_path
        user = get_user_model().objects.get(username="editora")
        form = MarkdownImageForm(
            data={"title": "Plenário", "alt_text": "Plenário da Câmara dos Deputados"},
            files={"image": image_file(640, 360, name="foto.png")},
        )

        assert form.is_valid(), form.errors
        image = form.save(commit=False)
        image.uploaded_by = user
        image.save()

        assert image.image.name == f"cms/markdown/{image.pk.hex}.webp"
        assert (image.width, image.height) == (640, 360)
        with Image.open(tmp_path / image.image.name) as stored:
            assert stored.format == "WEBP"

    def test_seletor_exige_login_e_exibe_imagens(self, admin_client, settings, tmp_path):
        settings.MEDIA_ROOT = tmp_path
        image = MarkdownImage.objects.create(
            title="Plenário",
            alt_text="Plenário da Câmara",
            image=image_file(320, 180),
        )
        url = reverse("admin:cms_markdownimage_chooser")

        assert Client().get(url).status_code == 302
        response = admin_client.get(url, {"q": "Plenário"})

        assert response.status_code == 200
        assert response["X-Frame-Options"] == "SAMEORIGIN"
        html = response.content.decode()
        assert "Plenário da Câmara" in html
        assert image.image.url in html
        assert "data-image-url=" in html

    def test_seletor_permite_enviar_e_escolher_no_mesmo_fluxo(
        self, admin_client, settings, tmp_path
    ):
        settings.MEDIA_ROOT = tmp_path
        response = admin_client.post(
            reverse("admin:cms_markdownimage_chooser"),
            {
                "title": "Comissão",
                "alt_text": "Deputadas reunidas em comissão",
                "image": image_file(400, 300),
            },
        )

        assert response.status_code == 200
        image = MarkdownImage.objects.get(title="Comissão")
        assert image.uploaded_by.username == "editora"
        assert image.image.url in response.content.decode()

    @pytest.mark.parametrize("page_model", [HomePage, FeministAIPage, AboutPage])
    def test_impede_excluir_imagem_referenciada(self, page_model, settings, tmp_path):
        settings.MEDIA_ROOT = tmp_path
        image = MarkdownImage.objects.create(
            title="Congresso",
            alt_text="Fachada do Congresso Nacional",
            image=image_file(320, 180),
        )
        page = page_model.objects.get(pk=1)
        page.content += f"\n\n![{image.alt_text}]({image.image.url})"
        page.save(update_fields=["content"])

        assert image.is_referenced
        assert not admin.site._registry[MarkdownImage].has_delete_permission(Mock(), image)
        with pytest.raises(ProtectedError, match="está em uso"):
            image.delete()

    def test_exclui_imagem_sem_referencia_e_seu_arquivo(self, settings, tmp_path):
        settings.MEDIA_ROOT = tmp_path
        image = MarkdownImage.objects.create(
            title="Congresso",
            alt_text="Fachada do Congresso Nacional",
            image=image_file(320, 180),
        )
        path = tmp_path / image.image.name

        image.delete()

        assert not MarkdownImage.objects.filter(pk=image.pk).exists()
        assert not path.exists()

    @pytest.mark.parametrize("model", [HomePage, FeministAIPage, AboutPage])
    def test_editor_markdown_recebe_o_seletor(self, admin_client, model):
        response = admin_client.get(reverse(f"admin:cms_{model._meta.model_name}_change", args=[1]))
        html = response.content.decode()

        assert reverse("admin:cms_markdownimage_chooser") in html
        assert "cms/js/markdown-image-chooser.js" in html
        assert "cms/css/markdown-components.css" in html


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
            *AboutPartner.objects.values_list("logo_image", flat=True),
        ]
        assert invalidated_paths(bucket.cloudfront) == [[f"/{key}*"] for key in keys]

    def test_no_bucket_nao_sobrescreve_substituicao(self, bucket):
        call_command("cms_publish_defaults", stdout=io.StringIO())

        bucket.put_object.assert_not_called()

    def test_force_regrava(self, bucket):
        call_command("cms_publish_defaults", "--force", stdout=io.StringIO())

        bucket.head_object.assert_not_called()
        assert bucket.put_object.call_count == 10 + AboutPartner.objects.count()


class TestFeministAIPage:
    def test_migracao_inicializa_pagina_publicada_e_tabelas(self):
        page = FeministAIPage.objects.get(pk=1)

        assert page.hero_title == "Quem foi **Maria Quitéria?**"
        assert page.architecture_card_1_highlight == "87% de acurácia"
        assert page.content.startswith("## Diferencial tecnológico")
        assert "Quem foi **Maria Quitéria?**" not in page.content
        assert "| Categoria | Conceito |" in page.content
        assert "### Arquitetura dos modelos" in page.content
        assert page.content.count(":::: cards 2") == 2
        assert page.content.splitlines().count("::: card") == 4
        assert "### Duas instâncias de supervisão" in page.content
        assert "### O que a QuitérIA ~~não faz~~" in page.content
        assert page.content.count("- ~~x~~ ") == 6
        assert "## desempenho do modelo" in page.content
        assert page.content.count("::: table transparent") == 4
        assert page.content.count(":::up:::") == 5
        assert page.content.count(":::down:::") == 2
        assert "#### Modelo de Desfavorabilidade" in page.content
        assert FeministAICategory.objects.filter(page=page).count() == 10
        assert FeministAIEvaluationMetric.objects.filter(page=page).count() == 8

    def test_api_devolve_documento_markdown_com_imagens_versionadas(self):
        response = Client().get("/api/v1/cms/feminist-ai")

        assert response.status_code == 200
        assert response["Cache-Control"] == "no-store"
        data = response.json()
        assert data["seo_title"].startswith("QuitérIA")
        assert data["title"] == "Quem foi **Maria Quitéria?**"
        assert data["subtitle"].startswith("O nome da ferramenta homenageia")
        assert data["hero_image"]["url"].startswith("/media/cms/ia-feminista/hero.webp?v=")
        assert data["content"].startswith("## Diferencial tecnológico")
        assert "/media/cms/ia-feminista/flow-desktop.webp?v=" in data["content"]
        assert "| Violências de Gênero |" in data["content"]

    def test_admin_separa_topo_do_editor_do_corpo(self, admin_client):
        url = reverse("admin:cms_feministaipage_change", args=[1])
        response = admin_client.get(url)
        html = response.content.decode()

        assert response.status_code == 200
        assert "Corpo da página em Markdown" in html
        assert 'name="content"' in html
        assert "unfold_markdown/js/easymde.min.js" in html
        assert "cms/js/markdown-components.js" in html
        assert "cms/css/markdown-components.css" in html
        assert 'name="seo_title"' in html
        assert 'name="seo_description"' in html
        assert 'name="hero_title"' in html
        assert 'name="hero_description"' in html
        assert 'name="hero_image"' in html
        assert 'name="feministaicategory_set-TOTAL_FORMS"' not in html

    def test_admin_salva_topo_e_markdown(self, admin_client):
        url = reverse("admin:cms_feministaipage_change", args=[1])
        page = FeministAIPage.objects.get(pk=1)
        content = page.content.replace("## Diferencial tecnológico", "## Tecnologia feminista")

        response = admin_client.post(
            url,
            {
                "seo_title": page.seo_title,
                "seo_description": page.seo_description,
                "hero_title": "Conheça a **QuitérIA**",
                "hero_description": page.hero_description,
                "content": content,
            },
        )

        assert response.status_code == 302, response.content.decode()[:1000]
        body = Client().get("/api/v1/cms/feminist-ai").json()
        assert body["title"] == "Conheça a **QuitérIA**"
        assert body["content"].startswith("## Tecnologia feminista")

    def test_formulario_usa_widget_markdown(self):
        form = FeministAIPageForm(instance=FeministAIPage.objects.get(pk=1))

        assert list(form.fields) == [
            "seo_title",
            "seo_description",
            "hero_title",
            "hero_description",
            "hero_image",
            "content",
        ]
        assert isinstance(form.fields["content"].widget, MarkdownWidget)
        assert isinstance(form.fields["content"].widget, FeministAIMarkdownWidget)
        assert "cms/js/markdown-components.js" in form.fields["content"].widget.media._js
        assert "cms/js/markdown-image-chooser.js" in form.fields["content"].widget.media._js


class TestAboutPage:
    def test_migracao_cria_hero_e_markdown_preservando_modelos_legados(self):
        page = AboutPage.objects.get(pk=1)

        assert page.seo_title == "Sobre o Elas no Congresso | AzMina"
        assert page.hero_title == "**Sobre** o **Elas** no **Congresso**"
        assert page.content.startswith("## A nossa história")
        assert page.content.count("::::: timeline") == 1
        assert page.content.splitlines().count("::: milestone") == 5
        assert page.content.count("::: rating ") == 4
        assert page.content.count("::: logo grid :::") == 1
        assert page.content.count("::: team :::") == 1
        assert ":::: expediente" not in page.content
        assert "Diego Rabatone Oliveira" not in page.content
        assert "Anis Bioética" not in page.content
        assert page.copy.count() == 171
        assert page.timeline.count() == 5
        assert page.challenges.count() == 5
        assert page.partners.count() == 25
        assert page.team_members.count() == 34
        assert set(page.team_members.values_list("group", flat=True)) == set(
            AboutTeamMember.Group.values
        )

    def test_api_separa_hero_markdown_e_parceiros(self):
        page = AboutPage.objects.get(pk=1)
        response = Client().get("/api/v1/cms/about")

        assert response.status_code == 200
        assert response["Cache-Control"] == "no-store"
        data = response.json()
        assert data["seo_title"] == page.seo_title
        assert data["title"] == page.hero_title
        assert data["subtitle"] == page.hero_description
        assert data["hero_image"]["url"].startswith("/media/cms/sobre/hero.webp?v=")
        assert data["content"].startswith("## A nossa história")
        assert "timeline" not in data
        assert "challenges" not in data
        assert "Anis Bioética" not in data["content"]
        assert data["partners"][0]["name"] == "Anis Bioética"
        assert data["partners"][0]["logo_url"].startswith("/media/cms/sobre/partners/anis.webp?v=")
        assert "asset_key" not in data["partners"][0]
        assert [group["key"] for group in data["team"]] == [
            "azmina",
            "suppliers",
            "governance",
            "validation",
            "previous",
        ]
        assert sum(len(group["members"]) for group in data["team"]) == 34
        assert data["team"][0]["members"][0] == {
            "name": "Diego Rabatone Oliveira",
            "role": "— Consultor de Desenvolvimento / ASK-AR",
        }
        assert data["team"][-1]["wide"] is True

    def test_grid_de_logos_usa_modelo_de_parceiros_sem_duplicar_no_markdown(self):
        page = AboutPage.objects.get(pk=1)
        partner = page.partners.first()
        partner.name = "Rede atualizada"
        partner.save(update_fields=["name"])

        data = Client().get("/api/v1/cms/about").json()

        assert data["content"].count("::: logo grid :::") == 1
        assert "Rede atualizada" not in data["content"]
        assert data["partners"][0]["name"] == "Rede atualizada"

    def test_admin_separa_topo_markdown_e_modelo_de_parceiros(self, admin_client):
        response = admin_client.get(reverse("admin:cms_aboutpage_change", args=[1]))
        html = response.content.decode()

        assert response.status_code == 200
        assert "Corpo da página em Markdown" in html
        assert 'name="hero_title"' in html
        assert 'name="hero_description"' in html
        assert 'name="content"' in html
        assert 'name="partners-TOTAL_FORMS"' in html
        assert 'name="team_members-TOTAL_FORMS"' in html
        assert 'name="timeline-TOTAL_FORMS"' not in html
        assert 'name="challenges-TOTAL_FORMS"' not in html
        assert AboutCopy not in admin.site._registry

    def test_formulario_usa_widget_markdown(self):
        form = AboutPageForm(instance=AboutPage.objects.get(pk=1))

        assert list(form.fields) == [
            "seo_title",
            "seo_description",
            "hero_title",
            "hero_description",
            "hero_image",
            "content",
        ]
        assert isinstance(form.fields["content"].widget, MarkdownWidget)
        assert isinstance(form.fields["content"].widget, CmsMarkdownWidget)

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
    @staticmethod
    def form_data(page, **updates):
        data = {
            "seo_title": page.seo_title,
            "seo_description": page.seo_description,
            "hero_title": page.hero_title,
            "hero_description": page.hero_description,
            "hero_cta_text": page.hero_cta_text,
            "content": page.content,
        }
        return data | updates

    def test_admin_reune_header_markdown_e_imagens(self, admin_client):
        response = admin_client.get(reverse("admin:cms_homepage_change", args=[1]))
        html = response.content.decode()

        assert response.status_code == 200
        assert "Corpo da página em Markdown" in html
        assert 'name="hero_title"' in html
        assert 'name="hero_description"' in html
        assert 'name="hero_cta_text"' in html
        assert 'name="hero_cta_url"' not in html
        assert 'name="content"' in html
        assert 'name="hero_image"' in html
        assert 'name="explore_image"' in html
        assert 'name="quiteria_image"' in html
        assert HomeCopy not in admin.site._registry

    def test_titulo_usa_widget_contornado_do_admin(self):
        form = HomePageForm(instance=HomePage.objects.get())

        assert isinstance(form.fields["hero_title"].widget, UnfoldAdminTextareaWidget)

    def test_admin_substitui_uma_imagem_sem_exigir_as_outras(self, admin_client, bucket):
        page = HomePage.objects.get()
        response = admin_client.post(
            reverse("admin:cms_homepage_change", args=[1]),
            self.form_data(page, hero_image=image_file(320, 180)),
        )

        assert response.status_code == 302
        page = HomePage.objects.get()
        assert page.hero_image.name == "cms/home/hero.webp"
        assert (page.hero_image_width, page.hero_image_height) == (320, 180)
        assert bucket.put_object.call_args.kwargs["Key"] == "cms/home/hero.webp"

    def test_migracao_e_api_preservam_header_markdown_e_componentes(self):
        assert HomePage.objects.filter(pk=1).exists()
        assert HomeCopy.objects.count() == 70

        response = Client().get("/api/v1/cms/home")

        assert response.status_code == 200
        assert response["Cache-Control"] == "no-store"
        data = response.json()
        assert data["title"] == ("**De olho** nas **pautas de gênero**\nno **Congresso Nacional**")
        assert "~~desfavoráveis~~" in data["subtitle"]
        assert data["cta_url"] == "#o-que-descobrimos"
        assert data["content"].count("::: chart ") == 5
        assert data["content"].count("::: proposals ") == 3
        assert "## Reportagens" in data["content"]
        assert "{percentual}" in data["content"]
        assert "HomeCopy" not in data
        assert data["hero_image"]["width"] == 513
        assert data["images"]["explore"]["width"] == 1440
        assert data["images"]["quiteria"]["height"] == 1080
        assert "charts" not in data and "news" not in data and "maps" not in data

    def test_markdown_editado_aparece_na_api_e_dispara_deploy(
        self, admin_client, deploy_task, django_capture_on_commit_callbacks
    ):
        page = HomePage.objects.get()
        content = page.content.replace("## Reportagens", "## Nossas reportagens")
        with django_capture_on_commit_callbacks(execute=True):
            response = admin_client.post(
                reverse("admin:cms_homepage_change", args=[page.pk]),
                self.form_data(page, content=content, _save="Salvar"),
            )

        assert response.status_code == 302
        assert "## Nossas reportagens" in Client().get("/api/v1/cms/home").json()["content"]
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
        assert Client().get("/api/v1/cms/footer-alerts").json()["title"] == ("Acompanhe os alertas")
