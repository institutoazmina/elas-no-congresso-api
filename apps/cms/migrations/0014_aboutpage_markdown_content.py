from django.db import migrations, models


def _link(label, url):
    return f"[{label}]({url})" if url else str(label)


def _milestone(item):
    description = item.description_before_link
    if item.link_text and item.link_url:
        description += _link(item.link_text, item.link_url)
    description += item.description_after_link
    return "\n\n".join(
        [
            "::: milestone",
            f"*{item.date_prefix}*",
            f"### {item.year}",
            description,
            f"**{item.tag}**",
            ":::",
        ]
    )


def _rating(variant, label, description):
    return "\n\n".join(
        [
            f"::: rating {variant}",
            f"#### {label}",
            description,
            ":::",
        ]
    )


def _card(title, text):
    return f"::: card\n#### {title}\n\n{text}\n:::"


def _credit(title, entries, *, wide=False):
    variant = " wide" if wide else ""
    items = "\n".join(f"- {entry}" for entry in entries)
    return f"::: credit{variant}\n### {title}\n\n{items}\n:::"


def _person(copy, name_key, role_key=None):
    name = copy[name_key]
    return f"**{name}** {copy[role_key]}" if role_key else name


def build_content(page):
    copy = {item.key: item.value.strip() for item in page.copy.order_by("position", "pk")}

    timeline = "\n\n".join(
        [
            "::::: timeline",
            ":::: milestones",
            *[_milestone(item) for item in page.timeline.order_by("position", "pk")],
            "::::",
            (
                f"> {_link(page.timeline_note_link_text, page.timeline_note_link_url)}"
                f"{page.timeline_note_after_link}"
            ),
            ":::::",
        ]
    )

    ratings = "\n\n".join(
        [
            ":::: ratings",
            _rating("favorable", copy["s02_029"], copy["s02_030"]),
            _rating("favorable-caveat", copy["s02_031"], copy["s02_032"]),
            _rating("unfavorable-caveat", copy["s02_033"], copy["s02_034"]),
            _rating("unfavorable", copy["s02_035"], copy["s02_036"]),
            "::::",
        ]
    )

    channels = "\n\n".join(
        [
            ":::: cards 3",
            _card(
                copy["s02_040"],
                f"{copy['s02_041']}  \n{_link(copy['s02_043'], copy['s02_042'])}",
            ),
            _card(copy["s02_044"], copy["s02_045"]),
            _card(
                copy["s02_046"],
                (
                    f"{copy['s02_047']} {_link(copy['s02_049'], copy['s02_048'])} "
                    f"{copy['s02_050']} **{copy['s02_051']}** {copy['s02_052']}"
                ),
            ),
            "::::",
        ]
    )

    challenges = [
        f"**{item.title} —** {item.text}" for item in page.challenges.order_by("position", "pk")
    ]

    team = [
        _person(copy, "s08_093", "s08_094"),
        _person(copy, "s08_095", "s08_096"),
        _person(copy, "s08_097", "s08_098"),
        _person(copy, "s08_099", "s08_100"),
        _person(copy, "s08_101", "s08_102"),
        _person(copy, "s08_103", "s08_104"),
    ]
    suppliers = [
        _person(copy, "s08_106", "s08_107"),
        _person(copy, "s08_108", "s08_109"),
        _person(copy, "s08_110", "s08_111"),
        _person(copy, "s08_112", "s08_113"),
        _person(copy, "s08_114", "s08_115"),
        _person(copy, "s08_116", "s08_117"),
    ]
    governance = [_person(copy, f"s08_{key}") for key in (119, 120, 121)]
    validation = [_person(copy, f"s08_{key}") for key in (123, 124, 125, 126)]
    previous = [
        _person(copy, "s08_128", "s08_129"),
        _person(copy, "s08_130", "s08_131"),
        _person(copy, "s08_132", "s08_133"),
        _person(copy, "s08_134", "s08_135"),
        _person(copy, "s08_136", "s08_x013"),
        _person(copy, "s08_137", "s08_138"),
        _person(copy, "s08_139", "s08_140"),
        _person(copy, "s08_141", "s08_142"),
        _person(copy, "s08_143", "s08_144"),
        _person(copy, "s08_145", "s08_146"),
        _person(copy, "s08_147", "s08_148"),
        _person(copy, "s08_149", "s08_150"),
        _person(copy, "s08_151", "s08_152"),
        _person(copy, "s08_153", "s08_154"),
        _person(copy, "s08_155", "s08_156"),
    ]
    credits = "\n\n".join(
        [
            ":::: expediente",
            _credit(copy["s08_092"], team),
            _credit(copy["s08_105"], suppliers),
            _credit(copy["s08_118"], governance),
            _credit(copy["s08_122"], validation),
            _credit(copy["s08_127"], previous, wide=True),
            "::::",
        ]
    )

    sections = [
        "\n\n".join(
            [
                f"## {copy['s01_007']}",
                copy["s01_008"],
                timeline,
            ]
        ),
        "\n\n".join(
            [
                f"## {copy['s02_009']}",
                copy["s02_010"],
                f"### {copy['s02_011']}",
                copy["s02_012"],
                (
                    "![Palavras-chave como stalking, meninas, útero, misoginia, "
                    "transexual e feminicídio alimentam a API de coleta.]"
                    "(/images/about/keyword-notes.svg)"
                ),
                (f"> {copy['s02_x004']} {_link(copy['s02_014'], copy['s02_013'])}."),
                f"### {copy['s02_022']}",
                copy["s02_023"],
                (f"> {copy['s02_x005']} {_link(copy['s02_025'], copy['s02_024'])}."),
                f"### {copy['s02_026']}",
                copy["s02_027"],
                copy["s02_028"],
                ratings,
                copy["s02_037"],
                f"### {copy['s02_038']}",
                copy["s02_039"],
                channels,
            ]
        ),
        "\n\n".join(
            [
                f"## {copy['s03_053']}",
                copy["s03_054"],
                copy["s03_055"],
                f"**{copy['s03_056']}**",
                "::: logo grid :::",
            ]
        ),
        "\n\n".join(
            [
                f"## {copy['s04_058']}",
                copy["s04_059"],
                "::: list arrows",
                f"- **{copy['s04_060']}**{copy['s04_061']}",
                f"- **{copy['s04_062']}**{copy['s04_063']}",
                f"- **{copy['s04_064']}**{copy['s04_065']}",
                ":::",
            ]
        ),
        "\n\n".join(
            [
                f"## {copy['s05_066']}",
                f"{copy['s05_x006']} *{copy['s05_067']}* {copy['s05_068']}",
                *challenges,
            ]
        ),
        "\n\n".join(
            [
                f"## {copy['s06_069']}",
                f"{copy['s06_070']} *{copy['s06_071']}* {copy['s06_072']}",
                copy["s06_073"],
                copy["s06_074"],
                (f"{copy['s06_x007']} {_link(copy['s06_076'], copy['s06_075'])}{copy['s06_077']}"),
                f"{copy['s06_x008']} {_link(copy['s06_079'], copy['s06_078'])}.",
            ]
        ),
        "\n\n".join(
            [
                f"## {copy['s07_080']}",
                (
                    f"{copy['s07_081']} *{copy['s07_082']}* {copy['s07_x009']} "
                    f"{_link(copy['s07_084'], copy['s07_083'])} {copy['s07_x010']}"
                ),
                (
                    f"**{copy['s07_x011']} {_link(copy['s07_086'], copy['s07_085'])}"
                    f"{copy['s07_x012']} {_link(copy['s07_088'], copy['s07_087'])}"
                    f"{copy['s07_089']}**"
                ),
                copy["s07_090"],
            ]
        ),
        "\n\n".join([f"## {copy['s08_091']}", credits]),
        "\n\n".join([f"## {copy['s09_157']}", copy["s09_158"]]),
    ]
    return "\n\n---\n\n".join(sections).strip() + "\n"


def populate_content(apps, schema_editor):
    model = apps.get_model("cms", "AboutPage")
    for page in model.objects.using(schema_editor.connection.alias).all():
        copy = {item.key: item.value.strip() for item in page.copy.all()}
        page.hero_title = (
            f"**{copy['s00_001']}** {copy['s00_002']} **{copy['s00_x001']}** "
            f"{copy['s00_x002']} **{copy['s00_003']}**"
        )
        page.hero_description = (
            f"{copy['s00_004']} {copy['s00_x003']} {copy['s00_005']} {copy['s00_006']}"
        )
        page.content = build_content(page)
        page.save(update_fields=["hero_title", "hero_description", "content"])


class Migration(migrations.Migration):
    dependencies = [("cms", "0013_feministaipage_content")]

    operations = [
        migrations.AddField(
            model_name="aboutpage",
            name="hero_title",
            field=models.CharField(max_length=160, null=True),
        ),
        migrations.AddField(
            model_name="aboutpage",
            name="hero_description",
            field=models.TextField(max_length=1200, null=True),
        ),
        migrations.AddField(
            model_name="aboutpage",
            name="content",
            field=models.TextField(null=True),
        ),
        migrations.RunPython(populate_content, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="aboutpage",
            name="hero_title",
            field=models.CharField(
                help_text="O topo é renderizado separadamente do conteúdo em Markdown.",
                max_length=160,
                verbose_name="Título (use **texto** para negrito)",
            ),
        ),
        migrations.AlterField(
            model_name="aboutpage",
            name="hero_description",
            field=models.TextField(
                help_text="Use **texto** para negrito.",
                max_length=1200,
                verbose_name="Descrição",
            ),
        ),
        migrations.AlterField(
            model_name="aboutpage",
            name="content",
            field=models.TextField(
                help_text=(
                    "Corpo da página em Markdown. Use ::: logo grid ::: e ::: team ::: somente "
                    "para posicionar os componentes; seus dados são mantidos nos campos abaixo. "
                    "HTML não é interpretado."
                ),
                verbose_name="Conteúdo",
            ),
        ),
    ]
