from django.db import migrations, models
from django.db.models import deletion

TEAM = {
    "azmina": [
        ("s08_093", "s08_094"),
        ("s08_095", "s08_096"),
        ("s08_097", "s08_098"),
        ("s08_099", "s08_100"),
        ("s08_101", "s08_102"),
        ("s08_103", "s08_104"),
    ],
    "suppliers": [
        ("s08_106", "s08_107"),
        ("s08_108", "s08_109"),
        ("s08_110", "s08_111"),
        ("s08_112", "s08_113"),
        ("s08_114", "s08_115"),
        ("s08_116", "s08_117"),
    ],
    "governance": [
        ("s08_119", None),
        ("s08_120", None),
        ("s08_121", None),
    ],
    "validation": [
        ("s08_123", None),
        ("s08_124", None),
        ("s08_125", None),
        ("s08_126", None),
    ],
    "previous": [
        ("s08_128", "s08_129"),
        ("s08_130", "s08_131"),
        ("s08_132", "s08_133"),
        ("s08_134", "s08_135"),
        ("s08_136", "s08_x013"),
        ("s08_137", "s08_138"),
        ("s08_139", "s08_140"),
        ("s08_141", "s08_142"),
        ("s08_143", "s08_144"),
        ("s08_145", "s08_146"),
        ("s08_147", "s08_148"),
        ("s08_149", "s08_150"),
        ("s08_151", "s08_152"),
        ("s08_153", "s08_154"),
        ("s08_155", "s08_156"),
    ],
}


def populate_team(apps, schema_editor):
    page_model = apps.get_model("cms", "AboutPage")
    member_model = apps.get_model("cms", "AboutTeamMember")
    alias = schema_editor.connection.alias

    for page in page_model.objects.using(alias).all():
        copy = {item.key: item.value.strip() for item in page.copy.all()}
        if not member_model.objects.using(alias).filter(page=page).exists():
            member_model.objects.using(alias).bulk_create(
                [
                    member_model(
                        page=page,
                        group=group,
                        position=position,
                        name=copy[name_key],
                        role=copy[role_key] if role_key else "",
                    )
                    for group, members in TEAM.items()
                    for position, (name_key, role_key) in enumerate(members, start=1)
                ]
            )

        section_start = page.content.find("## Expediente")
        section_end = page.content.find("\n\n---\n\n", section_start)
        if section_start >= 0 and section_end >= 0:
            section = page.content[section_start:section_end]
            if ":::: expediente" in section:
                heading = section.splitlines()[0]
                page.content = (
                    page.content[:section_start]
                    + f"{heading}\n\n::: team :::"
                    + page.content[section_end:]
                )
                page.save(update_fields=["content"])


class Migration(migrations.Migration):
    dependencies = [("cms", "0014_aboutpage_markdown_content")]

    operations = [
        migrations.CreateModel(
            name="AboutTeamMember",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "group",
                    models.CharField(
                        choices=[
                            ("azmina", "Equipe AzMina"),
                            ("suppliers", "Fornecedores"),
                            ("governance", "Comitê de Governança / QuitérIA"),
                            ("validation", "Comitê de Validação / QuitérIA"),
                            ("previous", "Edições anteriores"),
                        ],
                        max_length=20,
                        verbose_name="Grupo",
                    ),
                ),
                ("position", models.PositiveSmallIntegerField(verbose_name="Ordem no grupo")),
                ("name", models.CharField(max_length=160, verbose_name="Nome")),
                ("role", models.CharField(blank=True, max_length=240, verbose_name="Função")),
                (
                    "page",
                    models.ForeignKey(
                        on_delete=deletion.CASCADE,
                        related_name="team_members",
                        to="cms.aboutpage",
                    ),
                ),
            ],
            options={
                "verbose_name": "Integrante do expediente",
                "verbose_name_plural": "Integrantes do expediente",
                "db_table": "cms_about_team_member",
                "ordering": ["group", "position", "pk"],
            },
        ),
        migrations.RunPython(populate_team, migrations.RunPython.noop),
    ]
