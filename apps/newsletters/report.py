"""A factual Radar, frozen at the end of the reporting week."""

import re
import unicodedata
from datetime import date, datetime, time, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from django.db.models import Exists, OuterRef, Prefetch, Q
from markdown_it import MarkdownIt

from apps.activity.models import Vote
from apps.propositions.house_transfer import PUBLIC_ORIGIN_Q
from apps.propositions.models import Proposition, PropositionAuthor, PropositionEvent

REPORT_TZ = ZoneInfo("America/Sao_Paulo")
STAGES = {
    "law": ("📃", "Proposições que viraram lei (ou que estão próximas)"),
    "new": ("🆕", "Proposições que acabaram de chegar"),
    "processing": ("🔁", "Em tramitação nas Comissões"),
    "vote": ("🗳️", "Prontas para serem votadas"),
    "review": ("", "Status a revisar"),
}
# Câmara's official /referencias/proposicoes/codSituacao catalog. A chamber
# approval or transfer to the other house is deliberately not a law highlight.
CAMARA_LAW_CODES = {1070, 1140, 1150, 1160, 1294}
CAMARA_VOTE_CODES = {903, 924}
CAMARA_REVIEW_CODES = {923, 930, 931, 937, 940, 941, 950, 1120, 1222, 1292, 1360}
CAMARA_PROCESSING_CODES = {
    901,
    902,
    907,
    911,
    915,
    918,
    922,
    925,
    927,
    928,
    1170,
    1280,
    1295,
    1296,
    1297,
    1380,
}


def reporting_week(today: date) -> tuple[date, date]:
    end = today - timedelta(days=today.weekday())
    return end - timedelta(days=7), end


def boundaries(start, end):
    return datetime.combine(start, time.min, REPORT_TZ), datetime.combine(end, time.min, REPORT_TZ)


def folded(text):
    return " ".join(
        unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower().split()
    )


def classify(proposition, events, start, end, event_sources=None):
    """Use dated historical evidence, never today's undated status for an old week."""
    sources = event_sources or {}
    enacted = [
        source.enacted_at
        for source in [proposition, *sources.values()]
        if source.enacted_at and source.enacted_at < end
    ]
    if enacted:
        return "law", {"enacted_at": max(enacted).isoformat()}
    for event in reversed(events):
        house = sources.get(getattr(event, "proposition_id", None), proposition).house
        raw = event.raw_payload or {}
        code = raw.get("codSituacao") if house == "camara" else raw.get("idSituacaoIniciada")
        try:
            code = int(code) if code is not None else None
        except (TypeError, ValueError):
            code = None
        situation = folded(event.situation)
        movement = folded(" ".join(filter(None, [event.title, event.description, event.dispatch])))
        evidence = {
            "event_at": event.event_at.isoformat(),
            "source_event_id": event.source_event_id,
            "code": code,
            "situation": event.situation,
            "movement": movement,
        }
        if (house == "camara" and code in CAMARA_REVIEW_CODES) or any(
            word in situation
            for word in ("arquivad", "rejeitad", "retirad", "prejudicad", "vetad", "suspensa")
        ):
            return "review", evidence
        if (
            (house == "camara" and code in CAMARA_LAW_CODES)
            or (house == "senado" and code in {64, 92})
            or re.search(
                r"transformad[ao] em (norma|lei)|(?:aguardando|enviad[ao]|remetid[ao]|encaminhad[ao]).*(sancao|promulgacao)",
                situation + " " + movement,
            )
        ):
            return "law", evidence
        if (
            (house == "camara" and code in CAMARA_VOTE_CODES)
            or re.search(
                r"pronta? para (?:a )?pauta|aguardando deliberacao|incluid[ao] (?:na|em) (?:ordem do dia|pauta)",
                situation,
            )
            or re.search(
                r"(?:apresentacao|apresentad[ao]|recebid[ao]).*(?:parecer|relatorio)|(?:parecer|relatorio).*(?:apresentad[ao]|recebid[ao])",
                movement,
            )
        ):
            return "vote", evidence
        if (
            (house == "camara" and code in CAMARA_PROCESSING_CODES)
            or (
                event.committee_acronym
                and folded(event.committee_acronym) not in {"pleno", "plen", "mesa"}
                and not re.search(
                    r"apresentacao|apresentad[ao] (?:o |a )?(?:projeto|proposicao)", movement
                )
            )
            or re.search(
                r"comiss|aguardando (?:parecer|designacao de relator)|tramitando em conjunto",
                situation,
            )
        ):
            return "processing", evidence
        if re.search(
            r"(?:apresentacao|apresentad[ao]) (?:do |da |de |o |a )?(?:pl\b|pdl\b|pec\b|plp\b|pls\b|projeto|proposicao|proposta)",
            movement,
        ) or (
            house == "camara"
            and code in {905, 906, 912, 1010, 1080, 1290, 1302, 1383}
            and start <= proposition.presented_at < end
        ):
            return "new", evidence
        # A later unknown disposition must not inherit an earlier known stage.
        if situation or code is not None:
            return "review", evidence
    if start <= proposition.presented_at < end:
        return "new", {"presented_at": proposition.presented_at.isoformat()}
    return "review", {"reason": "Sem estágio oficial datado reconhecido"}


def official_url(proposition):
    value = proposition.tramitation_url or ""
    parsed = urlsplit(value)
    if (
        parsed.scheme in {"http", "https"}
        and parsed.hostname
        and (
            parsed.hostname == "camara.leg.br"
            or parsed.hostname.endswith(".camara.leg.br")
            or parsed.hostname == "senado.leg.br"
            or parsed.hostname.endswith(".senado.leg.br")
        )
    ):
        return value
    return ""


def build_snapshot(start, end):
    lower, upper = boundaries(start, end)
    propositions = (
        Proposition.objects.filter(PUBLIC_ORIGIN_Q)
        .filter(
            Q(presented_at__gte=start, presented_at__lt=end)
            | Q(enacted_at__gte=start, enacted_at__lt=end)
            | Q(transfers__enacted_at__gte=start, transfers__enacted_at__lt=end)
            | Q(
                Exists(
                    PropositionEvent.objects.filter(
                        proposition_id=OuterRef("pk"), event_at__gte=lower, event_at__lt=upper
                    )
                )
            )
            | Q(
                Exists(
                    PropositionEvent.objects.filter(
                        proposition__canonical_proposition_id=OuterRef("pk"),
                        event_at__gte=lower,
                        event_at__lt=upper,
                    )
                )
            )
            | Q(
                Exists(
                    Vote.objects.filter(
                        proposition_id=OuterRef("pk"), held_at__gte=lower, held_at__lt=upper
                    )
                )
            )
        )
        .distinct()
        .prefetch_related(
            Prefetch(
                "authors",
                queryset=PropositionAuthor.objects.select_related(
                    "parliamentarian", "institutional_author", "party"
                ).order_by("order_index", "pk"),
            ),
            Prefetch(
                "events",
                queryset=PropositionEvent.objects.filter(event_at__lt=upper).order_by(
                    "event_at", "sequence", "pk"
                ),
            ),
            Prefetch(
                "transfers__events",
                queryset=PropositionEvent.objects.filter(event_at__lt=upper).order_by(
                    "event_at", "sequence", "pk"
                ),
            ),
            "annotations",
            Prefetch("votes", queryset=Vote.objects.filter(held_at__gte=lower, held_at__lt=upper)),
        )
    )
    entries = []
    for proposition in propositions:
        transfers = list(proposition.transfers.all())
        sources = {source.pk: source for source in transfers}
        events = sorted(
            [
                *proposition.events.all(),
                *(event for source in transfers for event in source.events.all()),
            ],
            key=lambda event: (event.event_at, event.sequence, event.pk),
        )
        stage, evidence = classify(proposition, events, start, end, sources)
        current = transfers[-1] if transfers else proposition
        entries.append(
            {
                "id": proposition.pk,
                "house": proposition.house,
                "type": proposition.type_code.upper(),
                "number": proposition.number,
                "year": proposition.year,
                "identifier": f"{proposition.type_code.upper()} {proposition.number}/{proposition.year}",
                "ementa": proposition.ementa,
                "authors": [
                    {
                        "name": str(author.parliamentarian or author.institutional_author),
                        "institutional": author.parliamentarian_id is None,
                        "party": author.party.acronym if author.party else None,
                        "state": author.state_at_authorship,
                    }
                    for author in proposition.authors.all()
                ],
                "url": official_url(current),
                "stage": stage,
                "evidence": evidence,
                "is_approved": proposition.is_approved,
                "official_status": evidence.get("situation") or "",
                "annotations": [
                    {"category": a.category, "organization_id": a.organization_id}
                    for a in proposition.annotations.all()
                ],
                "week_events": [
                    {
                        "at": e.event_at.isoformat(),
                        "source_id": e.source_event_id,
                        "description": e.description,
                    }
                    for e in events
                    if lower <= e.event_at < upper
                ],
                "week_votes": [
                    {"at": v.held_at.isoformat(), "result": v.result}
                    for v in proposition.votes.all()
                    if lower <= v.held_at < upper
                ],
            }
        )
    return sorted(entries, key=lambda e: (e["type"], e["number"], e["year"], e["house"], e["id"]))


def escape_markdown(value):
    return re.sub(r"([\\`*_{}\[\]()<>!#|])", r"\\\1", " ".join((value or "").split()))


def render(entries, complete=True):
    parts = ["**LEGENDA**"] + [f"{emoji} {label}" for emoji, label in list(STAGES.values())[:4]]
    markdown = parts[0] + "\n\n" + "  \n".join(parts[1:]) + "\n\n"
    if not complete:
        markdown += "**Coleta incompleta — revisar cobertura antes de publicar.**\n\n"

    def entry_text(entry):
        emoji, label = STAGES[entry["stage"]]
        identifier = escape_markdown(entry["identifier"])
        url = entry["url"].replace("(", "%28").replace(")", "%29")
        link = f"[{identifier}](<{url}>)" if url else f"{identifier} (link oficial a revisar)"
        status = (
            label
            if entry["stage"] != "review"
            else f"Status a revisar: {escape_markdown(entry['official_status']) or 'não identificado'}"
        )
        authors = []
        for author in entry.get("authors", []):
            name = escape_markdown(author["name"])
            if not author["institutional"]:
                party = escape_markdown(author["party"]) or "partido não informado"
                state = escape_markdown(author["state"]) or "UF não informada"
                name += f" ({party}–{state})"
            authors.append(name)
        authors_text = "; ".join(authors) or "não informada"
        return (
            f"{emoji} **{escape_markdown(entry['ementa'])}** — {link} — {status}".strip()
            + f"  \n**Autoria:** {authors_text}."
        )

    for entry in entries:
        if entry["stage"] == "law":
            markdown += entry_text(entry) + "\n\n"
    for house, heading in [("camara", "Radar da Câmara"), ("senado", "Radar do Senado")]:
        markdown += f"## {heading}\n\n"
        house_entries = [
            e
            for stage in ["processing", "vote", "new", "review"]
            for e in entries
            if e["house"] == house and e["stage"] == stage
        ]
        if not house_entries:
            markdown += "Nenhuma movimentação registrada nesta seção.\n\n"
        for entry in house_entries:
            markdown += entry_text(entry) + "\n\n"
    return markdown, MarkdownIt("commonmark", {"html": False}).render(markdown)
