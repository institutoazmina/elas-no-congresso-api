from django.db import migrations
from django.utils import timezone


def disable_weekly_schedules(apps, schema_editor):
    periodic_task = apps.get_model("django_celery_beat", "PeriodicTask")
    periodic_tasks = apps.get_model("django_celery_beat", "PeriodicTasks")
    database = schema_editor.connection.alias
    updated = (
        periodic_task.objects.using(database)
        .filter(
            task__in=[
                "apps.subscriptions.tasks.send_weekly_digest",
                "apps.subscriptions.tasks.send_digest_email",
            ],
            enabled=True,
        )
        .update(enabled=False)
    )
    if updated:
        # Historical models do not emit the live model's scheduler-change signal.
        periodic_tasks.objects.using(database).update_or_create(
            ident=1, defaults={"last_update": timezone.now()}
        )


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0005_daily_digest"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(disable_weekly_schedules, migrations.RunPython.noop),
    ]
