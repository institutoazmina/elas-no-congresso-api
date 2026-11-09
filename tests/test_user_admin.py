import pytest
from django.contrib import admin
from django.contrib.auth.models import Group, User
from django.urls import reverse


def test_user_actions_bind_to_unfold():
    for model in (User, Group):
        model_admin = admin.site._registry[model]
        assert model_admin.action_form().fields["action"].widget.attrs.get("x-model") == "action"


@pytest.mark.django_db
def test_create_panel_user_with_role(admin_client):
    group = Group.objects.create(name="Editoria")
    url = reverse("admin:auth_user_add")
    response = admin_client.get(url)
    assert response.status_code == 200
    assert "groups" in response.context["adminform"].form.fields
    response = admin_client.post(
        url,
        {
            "username": "nova@example.org",
            "email": "nova@example.org",
            "first_name": "Nova",
            "last_name": "Editora",
            "password1": "UmaSenha-Forte-274!",
            "password2": "UmaSenha-Forte-274!",
            "usable_password": "true",
            "is_staff": "on",
            "is_active": "on",
            "groups": [group.pk],
            "_save": "Salvar",
        },
    )
    assert response.status_code == 302
    user = User.objects.get(username="nova@example.org")
    assert user.check_password("UmaSenha-Forte-274!")
    assert user.is_staff and user.is_active and not user.is_superuser
    assert list(user.groups.all()) == [group]


@pytest.mark.django_db
def test_user_list_exposes_creation_and_edit_form_preserves_roles(admin_client):
    group = Group.objects.create(name="Editoria")
    user = User.objects.create_user(username="editor", is_staff=True)
    user.groups.add(group)
    response = admin_client.get(reverse("admin:auth_user_changelist"))
    assert "Adicionar usuário e configurar acesso" in response.content.decode()
    assert 'title="Executar a ação selecionada"' in response.content.decode()
    response = admin_client.get(reverse("admin:auth_user_change", args=[user.pk]))
    assert response.status_code == 200
    form = response.context["adminform"].form
    assert list(form.initial["groups"]) == [group]
    assert form.fields["groups"].label == "Papéis (grupos de permissões)"


@pytest.mark.django_db
def test_delete_user_requires_confirmation(admin_client):
    user = User.objects.create_user(username="remove@example.org")
    url = reverse("admin:auth_user_changelist")
    data = {"action": "delete_selected", "_selected_action": [user.pk], "index": "0"}
    response = admin_client.post(url, data)
    assert response.status_code == 200
    assert User.objects.filter(pk=user.pk).exists()
    response = admin_client.post(url, {**data, "post": "yes"})
    assert response.status_code == 302
    assert not User.objects.filter(pk=user.pk).exists()


@pytest.mark.django_db
def test_staff_without_user_permissions_cannot_manage_users(client):
    user = User.objects.create_user(username="staff", is_staff=True)
    client.force_login(user)
    for route in ("admin:auth_user_add", "admin:auth_user_changelist"):
        assert client.get(reverse(route)).status_code == 403
