"""Context builders and renderers for subscription alert emails."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urljoin

from django.conf import settings
from django.template import Context, Engine, Template
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import SafeString

EMAIL_DIST_DIR = Path(__file__).resolve().parent / "emails" / "dist"
EMAIL_ASSETS = {"daily-header.png", "weekly-header.png", "header.png"}


def _absolute_url(path: str) -> str:
    """Turn a local API path into a public URL email clients can fetch."""
    return urljoin(f"{settings.SITE_BASE_URL.rstrip('/')}/", path.lstrip("/"))


def _header_url(name: str) -> str:
    if name not in EMAIL_ASSETS:
        raise ValueError(f"Asset de e-mail desconhecido: {name}")
    return _absolute_url(f"/api/v1/assets/emails/{name}")


@lru_cache
def _compiled_template(name: str) -> Template:
    """Load an MJML-generated HTML file shipped in the runtime image."""
    template_path = EMAIL_DIST_DIR / name
    try:
        source = template_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Template de e-mail não compilado: {template_path}. "
            "Execute `npm run build --prefix apps/subscriptions/emails`."
        ) from exc
    return Engine.get_default().from_string(source)


def _render_email(name: str, context: dict) -> str:
    return _compiled_template(name).render(Context(context))


def _proposition_url(proposition_id: int) -> str:
    return f"{settings.SITE_BASE_URL.rstrip('/')}/api/v1/propositions/{proposition_id}"


def _authors(proposition) -> tuple[str, str]:
    authors = proposition.authors.select_related(
        "parliamentarian", "institutional_author", "party"
    ).order_by("order_index")
    names: list[str] = []
    affiliations: list[str] = []
    for author in authors:
        if author.parliamentarian:
            names.append(str(author.parliamentarian))
        elif author.institutional_author:
            names.append(author.institutional_author.name)
        if author.party:
            affiliation = author.party.acronym
            if author.state_at_authorship:
                affiliation = f"{affiliation}/{author.state_at_authorship}"
            affiliations.append(affiliation)

    return ", ".join(names) or "Não informada", ", ".join(affiliations)


def _proposition_context(proposition) -> dict[str, str]:
    author, party_state = _authors(proposition)
    fallback_url = _proposition_url(proposition.pk)
    return {
        "titulo_curto": proposition.number_label,
        "tipo": proposition.type_code.upper(),
        "numero": f"{proposition.number}/{proposition.year}",
        "ementa": proposition.ementa,
        "autor": author,
        "partido_uf": party_state,
        "orgao": proposition.current_status or "não informado",
        "link_tramitacao": proposition.tramitation_url or fallback_url,
        "link_proposicao": fallback_url,
    }


def _base_context(subscription) -> dict[str, str | int]:
    base_url = settings.SITE_BASE_URL.rstrip("/")
    return {
        "ano": timezone.localdate().year,
        "link_acompanhar": settings.PUBLIC_SITE_URL.rstrip("/"),
        "link_descadastro": (
            f"{base_url}/api/v1/subscriptions/unsubscribe/{subscription.unsubscribe_token}"
        ),
    }


def render_daily_alert(subscription, proposition) -> str:
    context = _base_context(subscription)
    context.update(_proposition_context(proposition))
    context["daily_header_url"] = _header_url("daily-header.png")
    return _render_email("daily.html", context)


def _weekly_cards(propositions) -> SafeString:
    cards = []
    for proposition in propositions:
        item = _proposition_context(proposition)
        cards.append(
            format_html(
                '<div style="margin-top: 26px; font-size: 16px; line-height: 1.3;">'
                "<strong>{}</strong><br>"
                "{} {}<br>"
                "Ementa: {}.<br>"
                "Autoria: {} {}.<br>"
                '<span style="font-size: 20px; line-height: 0; vertical-align: -1px;">■</span> '
                "Você pode ler e acompanhar cada passo da tramitação por aqui:<br>"
                '<a href="{}" style="color: #000000; text-decoration: none;">{}</a>'
                "</div>",
                item["titulo_curto"],
                item["tipo"],
                item["numero"],
                item["ementa"],
                item["autor"],
                item["partido_uf"],
                item["link_tramitacao"],
                item["link_tramitacao"],
            )
        )
    return format_html_join("", "{}", ((card,) for card in cards))


def _weekly_themes_html(propositions) -> SafeString:
    cards = _weekly_cards(propositions)
    return format_html(
        '<div style="font-size: 16px; line-height: 1.3;">'
        '<div style="font-size: 18px; font-weight: 700; line-height: 1.2;">'
        "Proposições acompanhadas</div>"
        '<div style="margin-top: 23px; font-weight: 700;">'
        '<span style="font-size: 20px; line-height: 0; vertical-align: -1px;">■</span> '
        "Atualizações que chegaram nesta semana:</div>{}</div>",
        cards,
    )


def render_weekly_digest(subscription, propositions) -> str:
    context = _base_context(subscription)
    context.update(
        {
            "edicao": timezone.localdate().isocalendar().week,
            "data": timezone.localdate().strftime("%d/%m/%Y"),
            "temas_html": _weekly_themes_html(propositions),
            "weekly_header_url": _header_url("weekly-header.png"),
        }
    )
    return _render_email("weekly.html", context)


def render_confirmation_email(subscription) -> str:
    base_url = settings.SITE_BASE_URL.rstrip("/")
    context = {
        "ano": timezone.localdate().year,
        "confirmation_header_url": _header_url("header.png"),
        "link_confirmacao": f"{base_url}/api/v1/subscriptions/confirm/{subscription.confirm_token}",
    }
    return _render_email("confirmation.html", context)
