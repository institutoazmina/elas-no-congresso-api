from django.contrib import admin
from django_celery_beat.models import (
    ClockedSchedule,
    CrontabSchedule,
    IntervalSchedule,
    PeriodicTask,
    SolarSchedule,
)
from django_celery_results.models import GroupResult, TaskResult

# Resultados e agendamentos continuam ativos, fora do admin editorial.
admin.site.unregister(
    [
        TaskResult,
        GroupResult,
        PeriodicTask,
        ClockedSchedule,
        CrontabSchedule,
        IntervalSchedule,
        SolarSchedule,
    ]
)
