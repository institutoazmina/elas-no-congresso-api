"""Conteúdo inicial da página publicada, preservado para novas instalações."""

import json
from pathlib import Path

from django.db import migrations


def seed_content(apps, schema_editor):
    source = Path(__file__).resolve().parents[1] / "defaults" / "feminist-ai-content.json"
    content = json.loads(source.read_text(encoding="utf-8"))
    page_model = apps.get_model("cms", "FeministAIPage")
    page, _ = page_model.objects.using(schema_editor.connection.alias).get_or_create(
        pk=1, defaults=content["page"]
    )
    models = {
        "categories": "FeministAICategory",
        "limitations": "FeministAILimitation",
        "evaluation_metrics": "FeministAIEvaluationMetric",
        "evaluation_partitions": "FeministAIEvaluationPartition",
        "thematic_metrics": "FeministAIThematicMetric",
        "thematic_partitions": "FeministAIThematicPartition",
        "open_links": "FeministAIOpenLink",
    }
    for key, name in models.items():
        model = apps.get_model("cms", name)
        if not model.objects.using(schema_editor.connection.alias).filter(page_id=page.pk).exists():
            model.objects.using(schema_editor.connection.alias).bulk_create(
                [model(page_id=page.pk, **item) for item in content["items"][key]]
            )


class Migration(migrations.Migration):
    dependencies = [("cms", "0004_feminist_ai_page")]

    operations = [migrations.RunPython(seed_content, migrations.RunPython.noop)]
