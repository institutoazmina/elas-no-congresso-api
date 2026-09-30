# Generated manually for enacted-law metadata.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("propositions", "0008_proposition_event_history")]

    operations = [
        migrations.AddField(
            model_name="proposition",
            name="enacted_at",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="proposition",
            name="enacted_law_number",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="proposition",
            name="enacted_law_type",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="proposition",
            name="enacted_law_year",
            field=models.SmallIntegerField(blank=True, null=True),
        ),
    ]
