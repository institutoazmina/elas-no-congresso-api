from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('propositions', '0003_proposition_full_text'),
    ]

    operations = [
        # Backfill: linhas sem relevância viram 'relevante' antes do NOT NULL.
        migrations.RunSQL(
            "UPDATE proposition_annotations SET relevance = 'relevante' WHERE relevance IS NULL;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name='propositionannotation',
            name='relevance',
            field=models.CharField(
                choices=[
                    ('muito_relevante', 'Muito relevante'),
                    ('pouco_relevante', 'Pouco relevante'),
                    ('relevante', 'Relevante'),
                    ('saiu_de_pauta', 'Saiu de pauta'),
                ],
                default='relevante',
                max_length=20,
            ),
        ),
    ]
