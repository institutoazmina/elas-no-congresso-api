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

from apps.core.enums import PropositionCategory
from apps.propositions.celerity import calculate_celerity
from apps.propositions.models import PropositionAnalysis

EMAIL_DIST_DIR = Path(__file__).resolve().parent / "emails" / "dist"
EMAIL_ASSETS = {"daily-header.png", "header.png"}
CELERITY_ORDER = ("Tá voando", "Rápida", "Lenta", "Travada", "Esquecida")


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
    authors = proposition.authors.all()
    if "authors" not in getattr(proposition, "_prefetched_objects_cache", {}):
        authors = authors.select_related("parliamentarian", "institutional_author", "party")
    names: list[str] = []
    affiliations: list[str] = []
    for author in sorted(authors, key=lambda item: (item.order_index, item.pk)):
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
    """Compatibility wrapper for callers previewing a single proposition."""
    return render_daily_digest(subscription, [proposition])


def _daily_groups(propositions):
    """Human themes take precedence over successful AI analysis, as in matching."""
    groups = {}
    seen = set()
    for proposition in propositions:
        if proposition.pk in seen:
            continue
        seen.add(proposition.pk)
        categories = {annotation.category for annotation in proposition.annotations.all()}
        if not categories:
            analysis = getattr(proposition, "analysis", None)
            if analysis and analysis.analysis_status == PropositionAnalysis.Status.SUCCEEDED:
                categories = {analysis.theme_category} if analysis.theme_category else set()
        categories = categories.intersection(PropositionCategory.values) or {None}
        celerity = calculate_celerity(proposition, proposition.events.all()).label
        for category in categories:
            groups.setdefault(category, {}).setdefault(celerity, []).append(proposition)

    for category in (*PropositionCategory.values, None):
        if category not in groups:
            continue
        label = PropositionCategory(category).label if category else "Sem tema informado"
        yield (
            label,
            [
                (
                    celerity,
                    sorted(
                        groups[category][celerity], key=lambda prop: (prop.presented_at, prop.pk)
                    ),
                )
                for celerity in CELERITY_ORDER
                if celerity in groups[category]
            ],
        )


def _daily_card(proposition) -> tuple[dict, list[str]]:
    item = _proposition_context(proposition)
    affiliation = f" ({item['partido_uf']})" if item["partido_uf"] else ""
    lines = [
        f"Casa: {proposition.house}",
        f"Ementa: {item['ementa']}",
        f"Autoria: {item['autor']}{affiliation}.",
        f"Situação: {item['orgao']}.",
    ]
    for rapporteur in proposition.rapporteurs.all():
        if rapporteur.is_current:
            party = f" ({rapporteur.party.acronym})" if rapporteur.party else ""
            lines.append(f"Relatoria: {rapporteur.parliamentarian}{party}.")
    if proposition.regime:
        lines.append(f"Regime de tramitação: {proposition.regime}.")
    if proposition.enacted_law_number:
        law = str(proposition.enacted_law_number)
        if proposition.enacted_law_year:
            law = f"{law}/{proposition.enacted_law_year}"
        lines.append(f"Agora é {proposition.enacted_law_type or 'lei'} {law}.")
    return item, lines


def _daily_themes_html(propositions) -> SafeString:
    themes = []
    for theme, groups in _daily_groups(propositions):
        sections = []
        for celerity, props in groups:
            cards = []
            for proposition in props:
                item, lines = _daily_card(proposition)
                cards.append(
                    format_html(
                        '<div style="margin-top: 26px; font-size: 16px; line-height: 1.3;">'
                        "<strong>{}</strong><br>{} {}<br>{}"
                        "📄 Você pode ler e acompanhar cada passo da tramitação por aqui:<br>"
                        '<a href="{}" style="color: #000000; text-decoration: underline;">{}</a>'
                        "</div>",
                        item["titulo_curto"],
                        item["tipo"],
                        item["numero"],
                        format_html_join("", "{}<br>", ((line,) for line in lines)),
                        item["link_tramitacao"],
                        item["link_tramitacao"],
                    )
                )
            sections.append(
                format_html(
                    '<div style="margin-top: 23px; font-weight: 700;">Celeridade: {}</div>{}',
                    celerity,
                    format_html_join("", "{}", ((card,) for card in cards)),
                )
            )
        themes.append(
            format_html(
                '<div style="margin-bottom: 38px;">'
                '<div style="font-size: 18px; font-weight: 700; line-height: 1.2;">{}</div>{}</div>',
                theme,
                format_html_join("", "{}", ((section,) for section in sections)),
            )
        )
    return format_html_join("", "{}", ((theme,) for theme in themes))


def render_daily_digest(subscription, propositions) -> str:
    context = _base_context(subscription)
    context.update(
        {
            "data": timezone.localdate().strftime("%d/%m/%Y"),
            "temas_html": _daily_themes_html(propositions),
            "daily_header_url": _header_url("daily-header.png"),
        }
    )
    return _render_email("daily.html", context)


def render_daily_digest_text(subscription, propositions) -> str:
    lines = [
        "Olá,",
        "Esse é seu Radar do dia com todas as atualizações sobre as proposições "
        "e temas que você escolheu acompanhar.",
        timezone.localdate().strftime("%d/%m/%Y"),
    ]
    for theme, groups in _daily_groups(propositions):
        lines.append(f"\n{theme}")
        for celerity, props in groups:
            lines.append(f"\nCeleridade: {celerity}")
            for proposition in props:
                item, details = _daily_card(proposition)
                lines.extend(
                    [
                        f"\n{item['titulo_curto']}",
                        f"{item['tipo']} {item['numero']}",
                        *details,
                        "Você pode ler e acompanhar cada passo da tramitação por aqui:",
                        item["link_tramitacao"],
                    ]
                )
    context = _base_context(subscription)
    lines.extend(
        [
            f"\nAcompanhar proposições: {context['link_acompanhar']}",
            f"Cancelar inscrição: {context['link_descadastro']}",
        ]
    )
    return "\n".join(lines)


def render_confirmation_email(subscription) -> str:
    base_url = settings.SITE_BASE_URL.rstrip("/")
    context = {
        "ano": timezone.localdate().year,
        "confirmation_header_url": _header_url("header.png"),
        "link_confirmacao": f"{base_url}/api/v1/subscriptions/confirm/{subscription.confirm_token}",
    }
    return _render_email("confirmation.html", context)
