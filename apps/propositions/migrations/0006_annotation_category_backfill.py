"""Fecha `category` em NOT NULL com a restrição das Categorias 2026.

O preenchimento histórico a partir de planilha já foi aplicado nos ambientes
existentes; a planilha não faz mais parte do repositório. Em banco novo não há
anotações, e a migração só altera o schema. Se houver anotação sem categoria,
a migração aborta antes do ALTER, indicando quais linhas precisam de correção
no banco.
"""

from django.db import migrations, models

CHOICES = [
    ('violencias_de_genero', 'Violências de Gênero'),
    ('trabalho_economia_cuidado', 'Trabalho, Economia, Cuidado e Proteção Social'),
    ('direitos_sexuais_reprodutivos', 'Direitos Sexuais e Reprodutivos'),
    ('participacao_politica', 'Participação Política e Institucionalidade'),
    ('lgbtqiapn', 'LGBTQIAPN+'),
    ('saude', 'Saúde'),
    ('educacao_cultura', 'Educação e Cultura'),
    ('familia_parentalidade', 'Família, Parentalidade e Relações Civis'),
    ('infancia_adolescencia', 'Infância e Adolescência'),
    ('igualdade_antidiscriminacao', 'Igualdade e Antidiscriminação'),
]


def backfill(apps, schema_editor):
    model = apps.get_model('propositions', 'PropositionAnnotation')
    pendentes = list(
        model.objects.filter(category__isnull=True).values_list(
            'id', 'proposition__type_code', 'proposition__number',
            'proposition__year', 'organization__name',
        )[:21]
    )
    if pendentes:
        orfas = [
            f"  {type_code} {number}/{year} · {org} (pk={pk})"
            for pk, type_code, number, year, org in pendentes[:20]
        ]
        raise RuntimeError(
            "Anotações sem categoria; preencha `category` no banco antes de migrar:\n"
            + "\n".join(orfas)
            + ("\n  ..." if len(pendentes) > 20 else "")
        )


class Migration(migrations.Migration):

    dependencies = [
        ('propositions', '0005_annotation_category'),
    ]

    operations = [
        migrations.RunPython(backfill, reverse_code=migrations.RunPython.noop),
        migrations.AlterField(
            model_name='propositionannotation',
            name='category',
            field=models.CharField(choices=CHOICES, max_length=32),
        ),
        migrations.AddConstraint(
            model_name='propositionannotation',
            constraint=models.CheckConstraint(
                condition=models.Q(category__in=[value for value, _ in CHOICES]),
                name='proposition_annotations_category_check',
            ),
        ),
    ]
