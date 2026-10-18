"""Conteúdo da página Sobre publicada em 18/10/2026."""

import json
from pathlib import Path

from django.db import migrations


def seed_about(apps, schema_editor):
    source = Path(__file__).resolve().parents[1] / "defaults" / "about-content.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    alias = schema_editor.connection.alias
    page_model = apps.get_model("cms", "AboutPage")
    page, _ = page_model.objects.using(alias).get_or_create(
        pk=1,
        defaults={
            "seo_title": data["seo_title"],
            "seo_description": data["seo_description"],
            "timeline_note_link_text": data["timeline_note_link_text"],
            "timeline_note_link_url": data["timeline_note_link_url"],
            "timeline_note_after_link": data["timeline_note_after_link"],
        },
    )
    for name, key in [
        ("AboutCopy", "copy"),
        ("AboutTimelineEvent", "timeline"),
        ("AboutChallenge", "challenges"),
        ("AboutPartner", "partners"),
    ]:
        model = apps.get_model("cms", name)
        if not model.objects.using(alias).filter(page_id=page.pk).exists():
            model.objects.using(alias).bulk_create(
                [model(page_id=page.pk, **item) for item in data[key]]
            )


class Migration(migrations.Migration):
    dependencies = [("cms", "0006_aboutpage_aboutcopy_aboutchallenge_aboutpartner_and_more")]

    operations = [migrations.RunPython(seed_about, migrations.RunPython.noop)]
