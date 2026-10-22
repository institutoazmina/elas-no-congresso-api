from django.db import migrations, models


def _link(label, url):
    return f"[{label}]({url})"


def _container(name, *content):
    return "\n\n".join([f"::: {name}", *content, ":::"])


def _section(*content):
    return "\n\n".join(content)


def build_content(copy):
    sections = [
        _section(
            f"## {copy['rights_title']}",
            copy["rights_text"],
            "::: chart rights-under-attack :::",
            _container(
                "note",
                _link(copy["rights_postit_text"], copy["rights_postit_desktop_url"]),
                _link(copy["rights_postit_cta"], copy["rights_postit_mobile_url"]),
            ),
            _container("caption", copy["rights_caption"], copy["rights_footnote"]),
        ),
        _section(
            f"## {copy['setbacks_title']}",
            copy["setbacks_text"],
            "::: chart legislative-setbacks :::",
            _container("caption", _link(copy["setbacks_caption"], copy["setbacks_caption_url"])),
        ),
        _section(
            f"## {copy['reports_title']}",
            copy["reports_subtitle"],
            "::: reports :::",
        ),
        _section(
            f"## {copy['women_title']}",
            copy["women_text"],
            "::: chart women-in-defense :::",
            _container(
                "note",
                f"{copy['women_postit_before'].strip()} **{{percentual}}** "
                f"{copy['women_postit_after'].strip()}",
            ),
            _container("caption", copy["women_caption"]),
            _container("followup", copy["women_followup"]),
        ),
        _section(
            (
                f"## {copy['party_title_before'].strip()} "
                f"{{posição}} {copy['party_title_after'].strip()}"
            ),
            copy["party_subtitle"],
            "::: chart party-rights :::",
            _container("caption", _link(copy["party_caption"], copy["party_caption_url"])),
        ),
        _section(
            f"## {copy['uf_title']}",
            copy["uf_subtitle"],
            "::: chart state-projects :::",
            _container("caption", copy["uf_caption"]),
            _container("cta", _link(copy["uf_cta_text"], copy["uf_cta_url"])),
        ),
        _section(
            f"## {copy['alerts_title']}",
            copy["alerts_intro"],
            (
                f"{copy['alerts_detail_before'].strip()} "
                f"**{copy['alerts_detail_highlight']}** {copy['alerts_detail_after'].strip()}"
            ),
            "::: alerts :::",
            _container("cta", _link(copy["alerts_cta_text"], copy["alerts_cta_url"])),
        ),
        _section(
            f"## {copy['fast_title']}",
            copy["fast_subtitle"],
            "::: proposals fast :::",
        ),
        _section(
            f"## {copy['slow_title']}",
            copy["slow_subtitle"],
            "::: proposals slow :::",
        ),
        _section(
            f"## {copy['enacted_title']}",
            copy["enacted_subtitle"],
            "::: proposals enacted :::",
        ),
        _section(
            f"## {copy['explore_title']}",
            copy["explore_subtitle"],
            "::: explore :::",
            _container("image alt", copy["explore_image_alt"]),
            _container("cta", _link(copy["explore_cta_text"], copy["explore_cta_url"])),
        ),
        _section(
            f"## {copy['parliamentarians_title']}",
            copy["parliamentarians_subtitle"],
            "::: parliamentarians :::",
        ),
        _section(
            (
                f"{copy['quiteria_before_name'].strip()} **{copy['quiteria_name']}**"
                f"{copy['quiteria_between']}**{copy['quiteria_ai']}**{copy['quiteria_after']}"
            ),
            "::: quiteria :::",
            _container("image alt", copy["quiteria_image_alt"]),
            _container("cta", _link(copy["quiteria_cta_text"], copy["quiteria_cta_url"])),
        ),
    ]
    return "\n\n---\n\n".join(sections).strip() + "\n"


def populate_content(apps, schema_editor):
    model = apps.get_model("cms", "HomePage")
    alias = schema_editor.connection.alias
    for page in model.objects.using(alias).all():
        copy = {item.key: item.value for item in page.copy.order_by("position", "pk")}
        page.seo_title = copy["seo_title"]
        page.seo_description = copy["seo_description"]
        page.hero_title = (
            f"**{copy['hero_title_before_nas'].strip()}** {copy['hero_title_nas'].strip()} "
            f"**{copy['hero_title_after_nas'].strip()}**\n{copy['hero_title_no'].strip()} "
            f"**{copy['hero_title_after_no'].strip()}**"
        )
        page.hero_description = (
            f"{copy['hero_subtitle_before'].strip()} "
            f"~~{copy['hero_subtitle_highlight'].strip()}~~ "
            f"{copy['hero_subtitle_after'].strip()}"
        )
        page.hero_cta_text = copy["hero_scroll_text"]
        page.hero_cta_url = copy["hero_scroll_url"]
        page.content = build_content(copy)
        page.save(
            update_fields=[
                "seo_title",
                "seo_description",
                "hero_title",
                "hero_description",
                "hero_cta_text",
                "hero_cta_url",
                "content",
            ]
        )


class Migration(migrations.Migration):
    dependencies = [("cms", "0016_move_partner_logos_to_cms")]

    operations = [
        migrations.AddField(
            model_name="homepage",
            name="seo_title",
            field=models.CharField(max_length=160, null=True),
        ),
        migrations.AddField(
            model_name="homepage",
            name="seo_description",
            field=models.CharField(max_length=300, null=True),
        ),
        migrations.AddField(
            model_name="homepage",
            name="hero_title",
            field=models.TextField(max_length=160, null=True),
        ),
        migrations.AddField(
            model_name="homepage",
            name="hero_description",
            field=models.TextField(max_length=1200, null=True),
        ),
        migrations.AddField(
            model_name="homepage",
            name="hero_cta_text",
            field=models.CharField(max_length=80, null=True),
        ),
        migrations.AddField(
            model_name="homepage",
            name="hero_cta_url",
            field=models.CharField(max_length=500, null=True),
        ),
        migrations.AddField(
            model_name="homepage",
            name="content",
            field=models.TextField(null=True),
        ),
        migrations.RunPython(populate_content, migrations.RunPython.noop),
        migrations.AlterModelOptions(
            name="homepage",
            options={"verbose_name": "Home", "verbose_name_plural": "Home"},
        ),
        migrations.AlterField(
            model_name="homepage",
            name="seo_title",
            field=models.CharField(max_length=160, verbose_name="Título para buscas"),
        ),
        migrations.AlterField(
            model_name="homepage",
            name="seo_description",
            field=models.CharField(max_length=300, verbose_name="Descrição para buscas"),
        ),
        migrations.AlterField(
            model_name="homepage",
            name="hero_title",
            field=models.TextField(
                help_text="Use uma nova linha para forçar a quebra no título.",
                max_length=160,
                verbose_name="Título (use **texto** para negrito)",
            ),
        ),
        migrations.AlterField(
            model_name="homepage",
            name="hero_description",
            field=models.TextField(
                help_text=(
                    "Use **texto** para negrito e ~~texto~~ para destacar desfavorabilidade."
                ),
                max_length=1200,
                verbose_name="Descrição",
            ),
        ),
        migrations.AlterField(
            model_name="homepage",
            name="hero_cta_text",
            field=models.CharField(max_length=80, verbose_name="CTA de rolagem: texto"),
        ),
        migrations.AlterField(
            model_name="homepage",
            name="hero_cta_url",
            field=models.CharField(max_length=500, verbose_name="CTA de rolagem: destino"),
        ),
        migrations.AlterField(
            model_name="homepage",
            name="content",
            field=models.TextField(
                help_text=(
                    "Corpo da página em Markdown. Os marcadores ::: posicionam gráficos e "
                    "outros componentes dinâmicos. HTML não é interpretado."
                ),
                verbose_name="Conteúdo",
            ),
        ),
    ]
