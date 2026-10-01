from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("propositions", "0009_proposition_enactment"),
    ]

    operations = [
        # Itens existentes já estavam publicados antes deste controle e devem
        # permanecer visíveis. A alteração de default abaixo faz com que toda
        # proposição coletada daqui em diante entre pendente de aprovação.
        migrations.AddField(
            model_name="proposition",
            name="is_approved",
            field=models.BooleanField(db_index=True, default=True),
        ),
        migrations.AlterField(
            model_name="proposition",
            name="is_approved",
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
