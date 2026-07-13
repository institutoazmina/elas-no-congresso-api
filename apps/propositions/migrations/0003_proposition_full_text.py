from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('propositions', '0002_proposition_annotations'),
    ]

    operations = [
        migrations.AddField(
            model_name='proposition',
            name='full_text',
            field=models.TextField(blank=True, null=True),
        ),
    ]
