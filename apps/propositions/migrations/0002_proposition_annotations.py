import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('propositions', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='AssessmentOrganization',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.TextField(unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'assessment_organizations',
            },
        ),
        migrations.CreateModel(
            name='PropositionAnnotation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_favorable', models.BooleanField(blank=True, null=True)),
                ('has_caveats', models.BooleanField(default=False)),
                ('relevance', models.CharField(blank=True, choices=[('muito_relevante', 'Muito relevante'), ('pouco_relevante', 'Pouco relevante'), ('relevante', 'Relevante'), ('saiu_de_pauta', 'Saiu de pauta')], max_length=20, null=True)),
                ('assessment_score', models.SmallIntegerField(blank=True, null=True)),
                ('relevance_score', models.SmallIntegerField(blank=True, null=True)),
                ('human_theme', models.TextField(blank=True, null=True)),
                ('comments', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('proposition', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='annotations', to='propositions.proposition')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='annotations', to='propositions.assessmentorganization')),
            ],
            options={
                'db_table': 'proposition_annotations',
            },
        ),
    ]
