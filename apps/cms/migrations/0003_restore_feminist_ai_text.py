from django.db import migrations

REPLACEMENTS = (
    (
        "| [Métricas](https://ia.wiki.br/machine-learning/avaliacao/metricas/) | "
        "QuitérIA 1.0 (2025) | QuitérIA 2.0 (2026) | Tendência |",
        "| [Métricas](https://ia.wiki.br/machine-learning/avaliacao/metricas/) | "
        "QuitérIA 1.0 (2025) | QuitérIA 2.0 (2026) |  |",
    ),
    (
        "[F1 Score Índice 0](https://ia.wiki.br/machine-learning/avaliacao/metricas/pontuacao-f1/)",
        "[F1 Score](https://ia.wiki.br/machine-learning/avaliacao/metricas/pontuacao-f1/) Índice 0",
    ),
    (
        "[F1 Score Índice 1](https://ia.wiki.br/machine-learning/avaliacao/metricas/pontuacao-f1/)",
        "[F1 Score](https://ia.wiki.br/machine-learning/avaliacao/metricas/pontuacao-f1/) Índice 1",
    ),
    (
        "[Precisão Índice 0](https://ia.wiki.br/machine-learning/avaliacao/metricas/"
        "precisao-e-revocacao/)",
        "[Precisão](https://ia.wiki.br/machine-learning/avaliacao/metricas/"
        "precisao-e-revocacao/) Índice 0",
    ),
    (
        "[Precisão Índice 1](https://ia.wiki.br/machine-learning/avaliacao/metricas/"
        "precisao-e-revocacao/)",
        "[Precisão](https://ia.wiki.br/machine-learning/avaliacao/metricas/"
        "precisao-e-revocacao/) Índice 1",
    ),
    (
        "[Revocação Índice 0](https://ia.wiki.br/machine-learning/avaliacao/metricas/"
        "precisao-e-revocacao/)",
        "[Revocação](https://ia.wiki.br/machine-learning/avaliacao/metricas/"
        "precisao-e-revocacao/) Índice 0",
    ),
    (
        "[Revocação Índice 1](https://ia.wiki.br/machine-learning/avaliacao/metricas/"
        "precisao-e-revocacao/)",
        "[Revocação](https://ia.wiki.br/machine-learning/avaliacao/metricas/"
        "precisao-e-revocacao/) Índice 1",
    ),
    (
        "| Métricas | Valor |\n| --- | --- |\n| Acurácia | 0,82 |",
        "| Acurácia | 0,82 |\n| --- | --- |",
    ),
)


def replace_content(apps, replacements):
    page_model = apps.get_model("cms", "FeministAIPage")
    page = page_model.objects.filter(pk=1).first()
    if not page:
        return

    content = page.content
    for current, replacement in replacements:
        content = content.replace(current, replacement)
    if content != page.content:
        page.content = content
        page.save(update_fields=["content"])


def forwards(apps, schema_editor):
    replace_content(apps, REPLACEMENTS)


def backwards(apps, schema_editor):
    replace_content(apps, tuple((replacement, current) for current, replacement in REPLACEMENTS))


class Migration(migrations.Migration):
    dependencies = [("cms", "0002_hero_image_alt")]

    operations = [migrations.RunPython(forwards, backwards)]
