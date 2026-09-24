from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("propositions", "0006_annotation_category_backfill"),
    ]

    operations = [
        migrations.AddField(
            model_name="propositionanalysis",
            name="analysis_error",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="propositionanalysis",
            name="analysis_status",
            field=models.CharField(
                choices=[("pending", "Pendente"), ("succeeded", "Concluída"), ("failed", "Falhou")],
                default="pending",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="propositionanalysis",
            name="completed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="propositionanalysis",
            name="favorability_scores",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="propositionanalysis",
            name="input_hash",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="propositionanalysis",
            name="model_id",
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
        migrations.AddField(
            model_name="propositionanalysis",
            name="model_revision",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="propositionanalysis",
            name="theme_category",
            field=models.CharField(
                blank=True,
                choices=[
                    ("violencias_de_genero", "Violências de Gênero"),
                    ("trabalho_economia_cuidado", "Trabalho, Economia, Cuidado e Proteção Social"),
                    ("direitos_sexuais_reprodutivos", "Direitos Sexuais e Reprodutivos"),
                    ("participacao_politica", "Participação Política e Institucionalidade"),
                    ("lgbtqiapn", "LGBTQIAPN+"),
                    ("saude", "Saúde"),
                    ("educacao_cultura", "Educação e Cultura"),
                    ("familia_parentalidade", "Família, Parentalidade e Relações Civis"),
                    ("infancia_adolescencia", "Infância e Adolescência"),
                    ("igualdade_antidiscriminacao", "Igualdade e Antidiscriminação"),
                ],
                max_length=32,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="propositionanalysis",
            name="theme_confidence",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name="propositionanalysis",
            name="theme_scores",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddIndex(
            model_name="propositionanalysis",
            index=models.Index(fields=["analysis_status"], name="idx_analysis_status"),
        ),
    ]
