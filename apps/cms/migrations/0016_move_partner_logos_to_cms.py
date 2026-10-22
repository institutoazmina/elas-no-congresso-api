from django.db import migrations, models

import apps.cms.models
import apps.cms.storage


def set_partner_logos(apps, schema_editor):
    partner_model = apps.get_model("cms", "AboutPartner")
    alias = schema_editor.connection.alias
    for partner in partner_model.objects.using(alias).exclude(asset_key=""):
        partner.logo_image = f"cms/sobre/partners/{partner.asset_key}.webp"
        partner.save(update_fields=["logo_image"], using=alias)


class Migration(migrations.Migration):
    dependencies = [("cms", "0015_aboutteammember")]

    operations = [
        migrations.RunPython(set_partner_logos, migrations.RunPython.noop),
        migrations.RemoveField(model_name="aboutpartner", name="asset_key"),
        migrations.AlterModelOptions(
            name="aboutpage",
            options={"verbose_name": "Sobre", "verbose_name_plural": "Sobre"},
        ),
        migrations.AlterField(
            model_name="aboutpartner",
            name="logo_image",
            field=models.ImageField(
                help_text="PNG, JPEG ou WebP com até 5 MB. O logo se ajusta ao espaço disponível.",
                storage=apps.cms.storage.CmsStorage(),
                upload_to=apps.cms.models.partner_logo_path,
                verbose_name="Logo",
            ),
        ),
    ]
