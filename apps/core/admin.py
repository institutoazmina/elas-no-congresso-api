from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from django_celery_beat.models import (
    ClockedSchedule,
    CrontabSchedule,
    IntervalSchedule,
    PeriodicTask,
    SolarSchedule,
)
from django_celery_results.models import GroupResult, TaskResult
from unfold.admin import ModelAdmin
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm


class UserAccessFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["groups"].label = "Papéis (grupos de permissões)"
        self.fields["groups"].help_text = (
            "Selecione os papéis desta pessoa. Cada grupo reúne permissões de acesso. "
            "Os papéis disponíveis são configurados em Autenticação e Autorização → Grupos."
        )
        self.fields["is_staff"].label = "Acesso ao painel"
        self.fields[
            "is_staff"
        ].help_text = (
            "Permite entrar no painel. Os papéis e as permissões definem o que a pessoa pode fazer."
        )
        self.fields[
            "is_active"
        ].help_text = "Desmarque para suspender o acesso sem excluir a pessoa."


class PanelUserCreationForm(UserAccessFormMixin, UserCreationForm):
    pass


class PanelUserChangeForm(UserAccessFormMixin, UserChangeForm):
    pass


admin.site.unregister([User, Group])


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    form = PanelUserChangeForm
    add_form = PanelUserCreationForm
    change_password_form = AdminPasswordChangeForm
    list_before_template = "admin/auth/user/access_help.html"
    add_fieldsets = (
        ("Dados da pessoa", {"fields": ("username", "email", "first_name", "last_name")}),
        ("Senha de acesso", {"fields": ("password1", "password2")}),
        ("Acesso e papéis", {"fields": ("is_active", "is_staff", "groups")}),
    )


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass


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
