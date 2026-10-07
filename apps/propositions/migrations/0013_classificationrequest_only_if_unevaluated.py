from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "propositions",
            "0012_remove_propositioncontentversion_proposition_content_document_hash_and_more",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="classificationrequest",
            name="only_if_unevaluated",
            field=models.BooleanField(default=False),
        ),
    ]
