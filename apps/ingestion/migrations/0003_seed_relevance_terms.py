from django.db import migrations


def seed(apps, schema_editor):
    from apps.ingestion.theme_assert import _DEFAULT_COMBINED, _DEFAULT_STANDALONE

    RelevanceTerm = apps.get_model("ingestion", "RelevanceTerm")
    rows = [RelevanceTerm(term=t, mode="standalone") for t in _DEFAULT_STANDALONE]
    rows += [RelevanceTerm(term=t, mode="combined") for t in _DEFAULT_COMBINED]
    RelevanceTerm.objects.bulk_create(rows, ignore_conflicts=True)


def unseed(apps, schema_editor):
    RelevanceTerm = apps.get_model("ingestion", "RelevanceTerm")
    RelevanceTerm.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("ingestion", "0002_relevanceterm")]

    operations = [migrations.RunPython(seed, unseed)]
