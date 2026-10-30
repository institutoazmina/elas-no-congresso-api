import django.db.models.deletion
from django.db import migrations, models

# Pairs confirmed against the official Câmara and Senado process histories.
CONFIRMED_TRANSFERS = ((2335003, 176010), (2449135, 176022))


def link_confirmed_transfers(apps, schema_editor):
    Proposition = apps.get_model("propositions", "Proposition")
    db = schema_editor.connection.alias
    for camara_id, senado_id in CONFIRMED_TRANSFERS:
        original = (
            Proposition.objects.using(db).filter(house="camara", external_id=camara_id).first()
        )
        receiving = (
            Proposition.objects.using(db).filter(house="senado", external_id=senado_id).first()
        )
        if (
            original
            and receiving
            and original.type_code.upper() == receiving.type_code.upper() == "PL"
            and (original.number, original.year) == (receiving.number, receiving.year)
            and receiving.canonical_proposition_id is None
        ):
            Proposition.objects.using(db).filter(pk=receiving.pk).update(
                canonical_proposition_id=original.pk, originating_house="camara"
            )


class Migration(migrations.Migration):
    dependencies = [("propositions", "0015_ignoredproposition")]

    operations = [
        migrations.AddField(
            model_name="proposition",
            name="canonical_proposition",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="transfers",
                to="propositions.proposition",
                verbose_name="Proposição de origem",
            ),
        ),
        migrations.AddConstraint(
            model_name="proposition",
            constraint=models.CheckConstraint(
                condition=~models.Q(canonical_proposition=models.F("pk")),
                name="propositions_no_self_transfer",
            ),
        ),
        migrations.RunPython(link_confirmed_transfers, migrations.RunPython.noop),
    ]
