"""Preenche `category` a partir de tmp/categories-2026.csv e fecha em NOT NULL.

O backfill vive DENTRO da migração de propósito: um `migrate` deixa qualquer
ambiente consistente, e se algum par (proposição, avaliadora) não casar a
migração aborta antes do ALTER — em vez de o NOT NULL falhar com uma mensagem
do Postgres que não diz qual linha ficou de fora.

Casamento por (type_code, number, year, organization), nunca pelo `id` da
planilha — ver apps/propositions/categories.py.
"""

from collections import defaultdict

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
        )
    )
    if not pendentes:
        return

    # Import tardio: em banco vazio (testes, ambiente novo) nem se lê o arquivo.
    from apps.propositions.categories import load_category_map, proposition_fallback

    mapa = load_category_map()
    fallback = proposition_fallback(mapa)
    por_categoria = defaultdict(list)
    orfas = []
    por_fallback = 0
    for pk, type_code, number, year, org in pendentes:
        prop = ((type_code or '').upper(), number, year)
        categoria = mapa.get((*prop, org))
        if categoria is None:
            # Avaliadora divergente entre planilha e banco: cai na categoria da
            # proposição, se ela for única. Ambígua ou desconhecida -> órfã.
            categoria = fallback.get(prop)
            por_fallback += categoria is not None
        if categoria is None:
            orfas.append(f"  {type_code} {number}/{year} · {org} (pk={pk})")
        else:
            por_categoria[categoria].append(pk)

    if orfas:
        raise RuntimeError(
            f"{len(orfas)} anotações sem categoria em tmp/categories-2026.csv — "
            "regenere o mapa com scripts/build_category_map.py ou trate os casos:\n"
            + "\n".join(orfas[:20])
            + (f"\n  ... (+{len(orfas) - 20})" if len(orfas) > 20 else "")
        )

    for categoria, pks in por_categoria.items():
        model.objects.filter(pk__in=pks).update(category=categoria)
    print(
        f"  categorias preenchidas: {len(pendentes)} "
        f"({por_fallback} pela categoria da proposição, avaliadora divergente)"
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
