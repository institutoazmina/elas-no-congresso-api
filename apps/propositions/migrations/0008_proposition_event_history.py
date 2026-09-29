# Generated manually for legislative-event history.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("propositions", "0007_quiteria_analysis")]

    operations = [
        migrations.AddField(
            model_name="propositionevent",
            name="source_event_id",
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
        migrations.AddField(
            model_name="propositionevent",
            name="source_kind",
            field=models.CharField(default="status", max_length=32),
        ),
        migrations.AddField(
            model_name="propositionevent",
            name="title",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="propositionevent",
            name="committee_acronym",
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
        migrations.AddField(
            model_name="propositionevent",
            name="committee_name",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="propositionevent",
            name="is_countable",
            field=models.BooleanField(default=True),
        ),
        migrations.AddIndex(
            model_name="propositionevent",
            index=models.Index(fields=["proposition", "source_event_id"], name="idx_events_prop_source"),
        ),
        migrations.AddConstraint(
            model_name="propositionevent",
            constraint=models.UniqueConstraint(
                condition=models.Q(("source_event_id__isnull", False)),
                fields=("proposition", "source_event_id"),
                name="proposition_events_source_id",
            ),
        ),
    ]
