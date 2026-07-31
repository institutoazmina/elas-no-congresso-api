from django.db import migrations, models

# Categorias 2026: `human_theme` (texto livre, 107 variantes) sai de cena como
# campo de trabalho e vira `legacy_theme` (histórico, read-only no admin).
# A coluna nasce anulável só para o backfill da 0006, que a fecha em NOT NULL.


class Migration(migrations.Migration):

    dependencies = [
        ('propositions', '0004_annotation_relevance_not_null'),
    ]

    operations = [
        migrations.RenameField(
            model_name='propositionannotation',
            old_name='human_theme',
            new_name='legacy_theme',
        ),
        migrations.AddField(
            model_name='propositionannotation',
            name='category',
            field=models.CharField(
                choices=[
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
                ],
                max_length=32,
                null=True,
            ),
        ),
    ]
