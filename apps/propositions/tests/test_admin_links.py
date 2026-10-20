from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

from apps.propositions.admin_forms import PropositionLinksForm, parse_proposition_link

pytestmark = pytest.mark.django_db
URL = "admin:propositions_proposition_add_links"
CAMARA = "https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao=2632728"
SENADO = "https://www25.senado.leg.br/web/atividade/materias/-/materia/167294"


@pytest.mark.parametrize(
    ("link", "identity"),
    [
        (CAMARA, ("camara", 2632728)),
        ("https://www.camara.leg.br/propostas-legislativas/2624919", ("camara", 2624919)),
        (SENADO, ("senado", 167294)),
        ("https://legis.senado.leg.br/dadosabertos/materia/167294", ("senado", 167294)),
    ],
)
def test_official_links_identify_proposition(link, identity):
    assert parse_proposition_link(link) == identity


@pytest.mark.parametrize(
    "link",
    [
        "https://www.camara.leg.br.evil.test/proposicoesWeb/fichadetramitacao?idProposicao=1",
        "http://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao=1",
        "https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao=abc",
        "https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao=1&idProposicao=2",
        "https://www25.senado.leg.br/web/atividade/materias/-/materia/1/extra",
        "https://www.camara.leg.br:bad/propostas-legislativas/1",
    ],
)
def test_invalid_links_are_rejected(link):
    assert not PropositionLinksForm({"links": link}).is_valid()


def test_form_deduplicates_and_rejects_whole_batch_on_error():
    form = PropositionLinksForm({"links": f"{CAMARA}\n{CAMARA}\n{SENADO}"})
    assert form.is_valid()
    assert form.cleaned_data["links"] == [("camara", 2632728), ("senado", 167294)]

    invalid = PropositionLinksForm({"links": f"{CAMARA}\nhttps://example.com/1"})
    assert not invalid.is_valid()
    assert "Linha 2" in str(invalid.errors)


def staff_user(*, can_add):
    user = get_user_model().objects.create_user(username="staff", is_staff=True)
    if can_add:
        user.user_permissions.add(Permission.objects.get(codename="add_proposition"))
    return user


def test_admin_requires_add_permission_and_shows_link_form():
    client = Client()
    assert client.get(reverse(URL)).status_code == 302
    client.force_login(staff_user(can_add=False))
    assert client.get(reverse(URL)).status_code == 403

    user = get_user_model().objects.get(username="staff")
    user.user_permissions.add(Permission.objects.get(codename="add_proposition"))
    client.force_login(user)
    response = client.get(reverse(URL))
    assert response.status_code == 200
    assert "Adicionar proposições por link" in response.content.decode()
    assert 'name="csrfmiddlewaretoken"' in response.content.decode()


def test_admin_posts_validated_ids_once_and_redirects():
    client = Client()
    client.force_login(staff_user(can_add=True))
    with patch(
        "apps.propositions.admin.enqueue_manual_links", return_value=[SimpleNamespace(pk=8)]
    ) as enqueue:
        response = client.post(reverse(URL), {"links": f"{CAMARA}\n{CAMARA}"})
    assert response.status_code == 302
    assert response.url == reverse("admin:propositions_proposition_changelist")
    enqueue.assert_called_once_with([("camara", 2632728)])


def test_admin_invalid_batch_enqueues_nothing():
    client = Client()
    client.force_login(staff_user(can_add=True))
    with patch("apps.propositions.admin.enqueue_manual_links") as enqueue:
        response = client.post(reverse(URL), {"links": f"{CAMARA}\nhttps://example.com/1"})
    assert response.status_code == 200
    assert "Linha 2" in response.content.decode()
    enqueue.assert_not_called()


def test_admin_requires_csrf():
    client = Client(enforce_csrf_checks=True)
    client.force_login(staff_user(can_add=True))
    with patch("apps.propositions.admin.enqueue_manual_links") as enqueue:
        assert client.post(reverse(URL), {"links": CAMARA}).status_code == 403
    enqueue.assert_not_called()
