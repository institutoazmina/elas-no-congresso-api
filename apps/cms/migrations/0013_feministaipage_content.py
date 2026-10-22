from django.db import migrations, models


def _cell(value):
    return str(value).replace("\n", " ").replace("|", "\\|").strip()


def _table(headers, rows):
    head = "| " + " | ".join(_cell(value) for value in headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(_cell(value) for value in row) + " |" for row in rows]
    return "\n".join([head, separator, *body])


def _transparent_table(headers, rows):
    return f"::: table transparent\n\n{_table(headers, rows)}\n\n:::"


def _link(label, url):
    return f"[{label}]({url})" if url else str(label)


def _card(*parts):
    content = "\n\n".join(str(part).strip() for part in parts if str(part).strip())
    return f"::: card\n{content}\n:::"


def _cards(columns, cards):
    return f":::: cards {columns}\n\n" + "\n\n".join(cards) + "\n\n::::"


def build_content(page):
    categories = page.feministaicategory_set.order_by("position", "pk")
    limitations = page.feministailimitation_set.order_by("position", "pk")
    evaluation_metrics = page.feministaievaluationmetric_set.order_by("position", "pk")
    evaluation_partitions = page.feministaievaluationpartition_set.order_by("position", "pk")
    thematic_metrics = page.feministaithematicmetric_set.order_by("position", "pk")
    thematic_partitions = page.feministaithematicpartition_set.order_by("position", "pk")
    open_links = page.feministaiopenlink_set.order_by("position", "pk")

    trend = {"up": ":::up:::", "down": ":::down:::", "neutral": "–"}
    sections = [
        "\n\n".join(
            [
                f"## {page.differential_heading}",
                page.differential_paragraph_1,
                page.differential_paragraph_2,
                page.differential_paragraph_3,
                f"### {page.flow_heading}",
                f"![{page.flow_image_alt}](/media/{page.flow_desktop_image.name})",
                f"### {page.architecture_heading}",
                _cards(
                    2,
                    [
                        _card(
                            f"#### {page.architecture_card_1_title}",
                            page.architecture_card_1_text,
                            f"**{page.architecture_card_1_highlight}**",
                            f"> {page.architecture_card_1_note}",
                        ),
                        _card(
                            f"#### {page.architecture_card_2_title}",
                            page.architecture_card_2_text,
                        ),
                    ],
                ),
            ]
        ),
        "\n\n".join(
            [
                f"## {page.feminism_heading}",
                (
                    f"{page.feminism_paragraph_1_before_link} "
                    f"{_link(page.feminism_paragraph_1_link_text, page.feminism_paragraph_1_link_url)}"
                    f"{page.feminism_paragraph_1_after_link}"
                ),
                page.feminism_paragraph_2,
                (
                    f"{page.feminism_paragraph_3_before_highlight} "
                    f"**{page.feminism_paragraph_3_highlight}** "
                    f"{page.feminism_paragraph_3_after_highlight}"
                ),
                f"### {page.categories_heading}",
                _table(
                    [page.categories_name_column, page.categories_concept_column],
                    [(item.name, item.concept) for item in categories],
                ),
            ]
        ),
        "\n\n".join(
            [
                f"## {page.governance_heading}",
                (
                    f"{page.governance_paragraph_1_before_link} "
                    f"{_link(page.governance_paragraph_1_link_text, page.governance_paragraph_1_link_url)}"
                    f"{page.governance_paragraph_1_after_link}"
                ),
                page.governance_paragraph_2,
                f"### {page.supervision_heading}",
                _cards(
                    2,
                    [
                        _card(
                            f"#### {page.supervision_card_1_title}",
                            page.supervision_card_1_text,
                            f"> {page.supervision_card_1_note}",
                        ),
                        _card(
                            f"#### {page.supervision_card_2_title}",
                            page.supervision_card_2_text,
                            f"> {page.supervision_card_2_note}",
                        ),
                    ],
                ),
                f"### {page.limitations_heading.replace('não faz', '~~não faz~~')}",
                page.limitations_intro,
                "\n".join(f"- ~~x~~ {item.text}" for item in limitations),
            ]
        ),
        "\n\n".join(
            [
                f"## {page.performance_heading}",
                f"### {page.evaluation_caption}",
                _transparent_table(
                    [
                        _link(page.evaluation_metric_column, page.evaluation_metric_help_url),
                        page.evaluation_previous_column,
                        page.evaluation_current_column,
                        "Tendência",
                    ],
                    [
                        (
                            _link(item.label, item.url),
                            item.previous,
                            item.current,
                            trend.get(item.trend, "–"),
                        )
                        for item in evaluation_metrics
                    ],
                ),
                f"### {page.evaluation_partition_caption}",
                _transparent_table(
                    [
                        page.evaluation_partition_name_column,
                        page.evaluation_partition_accuracy_column,
                        page.evaluation_partition_percent_column,
                        page.evaluation_partition_count_column,
                    ],
                    [
                        (item.label, item.accuracy, item.percentage, item.count)
                        for item in evaluation_partitions
                    ],
                ),
                f"### {page.thematic_caption}",
                _transparent_table(
                    [page.evaluation_metric_column, "Valor"],
                    [(item.label, item.value) for item in thematic_metrics],
                ),
                f"### {page.thematic_partition_caption}",
                _transparent_table(
                    [
                        page.thematic_partition_name_column,
                        page.thematic_partition_training_column,
                        page.thematic_partition_validation_column,
                        page.thematic_partition_test_column,
                    ],
                    [
                        (item.label, item.training, item.validation, item.test)
                        for item in thematic_partitions
                    ],
                ),
            ]
        ),
        "\n\n".join(
            [
                f"## {page.open_data_heading}",
                page.open_data_intro,
                "\n".join(f"- {_link(item.label, item.url)}" for item in open_links),
            ]
        ),
    ]
    return "\n\n---\n\n".join(sections).strip() + "\n"


def populate_content(apps, schema_editor):
    model = apps.get_model("cms", "FeministAIPage")
    for page in model.objects.using(schema_editor.connection.alias).all():
        page.content = build_content(page)
        page.save(update_fields=["content"])


class Migration(migrations.Migration):
    dependencies = [("cms", "0012_remove_feministaipage_hero_title_emphasis_and_more")]

    operations = [
        migrations.AddField(
            model_name="feministaipage",
            name="content",
            field=models.TextField(
                help_text=(
                    "O corpo da página em Markdown: títulos, parágrafos, imagens, divisores, "
                    "tabelas, listas, links e grupos de cards. HTML não é interpretado."
                ),
                null=True,
                verbose_name="Conteúdo",
            ),
        ),
        migrations.RunPython(populate_content, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="feministaipage",
            name="content",
            field=models.TextField(
                help_text=(
                    "O corpo da página em Markdown: títulos, parágrafos, imagens, divisores, "
                    "tabelas, listas, links e grupos de cards. HTML não é interpretado."
                ),
                verbose_name="Conteúdo",
            ),
        ),
    ]
