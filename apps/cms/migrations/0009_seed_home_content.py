"""Conteúdo editorial da home publicada em 18/10/2026."""

import json
from pathlib import Path

from django.db import migrations


def seed_home(apps, schema_editor):
    source = Path(__file__).resolve().parents[1] / "defaults" / "home-content.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    alias = schema_editor.connection.alias
    page_model = apps.get_model("cms", "HomePage")
    page, _ = page_model.objects.using(alias).get_or_create(pk=1)
    copy_model = apps.get_model("cms", "HomeCopy")
    if not copy_model.objects.using(alias).filter(page_id=page.pk).exists():
        copy_model.objects.using(alias).bulk_create(
            [copy_model(page_id=page.pk, **item) for item in data["copy"]]
        )
    apps.get_model("cms", "FooterAlertsPage").objects.using(alias).get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [("cms", "0008_footeralertspage_homepage_homecopy")]

    operations = [migrations.RunPython(seed_home, migrations.RunPython.noop)]
