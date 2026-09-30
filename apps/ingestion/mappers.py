"""Tradução dos payloads brutos das APIs para os campos dos modelos do domínio.

Substitui rename_cols_camara.py / rename_cols_senado.py / df_config.py do bot.
Cada ``map_*`` devolve dicts prontos para ``update_or_create``/``create``.
"""

import json
import re
from datetime import date, datetime
from hashlib import sha256

from django.utils import timezone

from apps.core.enums import Gender, House

# ── helpers ──────────────────────────────────────────────────────────────────

def _map_gender(raw: str | None) -> str | None:
    """Normaliza sexo das APIs ('M'/'F'/'Masculino'/'Feminino') → Gender."""
    if not raw:
        return None
    r = raw.strip().lower()
    if r in ("m", "masculino"):
        return Gender.M
    if r in ("f", "feminino"):
        return Gender.F
    return None


def _to_int(val) -> int | None:
    try:
        return int(str(val).strip()) if val not in (None, "") else None
    except (ValueError, TypeError):
        return None


def _parse_date(val: str | None) -> date | None:
    if not val:
        return None
    val = str(val).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(val[: len(fmt) + 2], fmt).date()
        except ValueError:
            continue
    # ISO com timezone/offset
    try:
        return datetime.fromisoformat(val).date()
    except ValueError:
        return None


def _parse_datetime(val: str | None) -> datetime | None:
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(str(val).strip())
    except ValueError:
        d = _parse_date(val)
        dt = datetime(d.year, d.month, d.day) if d else None
    if dt and timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


_DEPUTY_ID_RE = re.compile(r"/deputados/(\d+)")
_LAW_RE = re.compile(
    r"\b(?P<type>lei(?:\s+(?:complementar|ordin[áa]ria))?)\s*"
    r"(?:n[ºo°.]?\s*)?(?P<number>\d[\d.]*)\s*(?:/|,?\s+de\s+)(?P<year>\d{4})",
    re.IGNORECASE,
)
_SENADO_ENACTED_STATUS_CODES = {64, 92}


def _law_metadata(texts: list[object], enacted_at: date | None) -> dict | None:
    """Extract a law identifier explicitly present in an official event."""
    for text in texts:
        if not isinstance(text, str):
            continue
        match = _LAW_RE.search(text)
        if not match:
            continue
        number = _to_int(match.group("number").replace(".", ""))
        year = _to_int(match.group("year"))
        if number is None or year is None or enacted_at is None:
            continue
        law_type = " ".join(match.group("type").split()).title()
        return {
            "enacted_law_type": law_type,
            "enacted_law_number": number,
            "enacted_law_year": year,
            "enacted_at": enacted_at,
        }
    return None


# ── Câmara ───────────────────────────────────────────────────────────────────

def map_camara_proposition(summary: dict, detail: dict) -> dict:
    """summary (lista) + detail (/proposicoes/{id}) → kwargs de Proposition."""
    status = detail.get("statusProposicao", {}) or {}
    sigla = summary.get("siglaTipo") or detail.get("siglaTipo") or ""
    numero = _to_int(summary.get("numero") or detail.get("numero")) or 0
    ano = _to_int(summary.get("ano") or detail.get("ano")) or 0
    external_id = _to_int(summary.get("id"))

    return {
        "house": House.CAMARA,
        "external_id": external_id,
        "type_code": sigla,
        "number_label": f"{sigla} {numero}/{ano}".strip(),
        "number": numero,
        "year": ano,
        "presented_at": _parse_date(detail.get("dataApresentacao")),
        "ementa": summary.get("ementa") or detail.get("ementa") or "",
        "keywords": detail.get("keywords"),
        "full_text_url": detail.get("urlInteiroTeor"),
        "tramitation_url": f"https://www.camara.leg.br/propostas-legislativas/{external_id}",
        "current_status": status.get("descricaoSituacao"),
        "current_status_code": _to_int(status.get("codSituacao")),
        "regime": status.get("regime"),
        "scope": status.get("ambito"),
        "appreciation_mode": status.get("apreciacao"),
        "raw_payload": detail,
    }


def map_camara_event(detail: dict) -> dict | None:
    """Última movimentação (statusProposicao) → kwargs de PropositionEvent."""
    status = detail.get("statusProposicao", {}) or {}
    event_at = _parse_datetime(status.get("dataHora"))
    if not event_at:
        return None
    return {
        "source_event_id": _source_id("camara", status.get("sequencia"), status),
        "source_kind": "tramitation",
        "event_at": event_at,
        "sequence": _to_int(status.get("sequencia")),
        "title": status.get("descricaoTramitacao"),
        "description": status.get("descricaoTramitacao"),
        "situation": status.get("descricaoSituacao"),
        "dispatch": status.get("despacho"),
        "committee_acronym": status.get("siglaOrgao"),
        "committee_name": status.get("nomeOrgao"),
        "raw_payload": status,
    }


def map_camara_events(tramitations: list[dict]) -> list[dict]:
    """Normaliza todas as tramitações oficiais da Câmara."""
    events = []
    for tramitation in tramitations:
        event_at = _parse_datetime(tramitation.get("dataHora"))
        if not event_at:
            continue
        events.append(
            {
                "source_event_id": _source_id(
                    "camara", tramitation.get("sequencia"), tramitation
                ),
                "source_kind": "tramitation",
                "event_at": event_at,
                "sequence": _to_int(tramitation.get("sequencia")),
                "title": tramitation.get("descricaoTramitacao"),
                "description": tramitation.get("descricaoTramitacao"),
                "situation": tramitation.get("descricaoSituacao"),
                "dispatch": tramitation.get("despacho"),
                "committee_acronym": tramitation.get("siglaOrgao"),
                "committee_name": tramitation.get("nomeOrgao"),
                "raw_payload": tramitation,
            }
        )
    return events


def map_camara_enactment(detail: dict, tramitations: list[dict]) -> dict | None:
    """Extract confirmed enactment metadata from the official Câmara timeline."""
    status = detail.get("statusProposicao", {}) or {}
    if _to_int(status.get("codSituacao")) != 1140:
        return None

    terminal = next(
        (
            tramitation
            for tramitation in reversed(tramitations)
            if _to_int(tramitation.get("codSituacao")) == 1140
        ),
        status,
    )
    enacted_at = _parse_date(terminal.get("dataHora") or status.get("dataHora"))
    return _law_metadata(
        [
            terminal.get("descricaoTramitacao"),
            terminal.get("despacho"),
            terminal.get("descricaoSituacao"),
        ],
        enacted_at,
    )


def parse_camara_authors(authors: list[dict]) -> list[dict]:
    """Normaliza autores da Câmara em ``{name, kind, external_id, party, state, gender, order}``.

    ``party``/``state``/``gender`` ficam None aqui — são preenchidos por
    ``enrich_camara_author`` a partir do detalhe do deputado.
    """
    out = []
    for i, a in enumerate(authors, start=1):
        uri = a.get("uri") or ""
        m = _DEPUTY_ID_RE.search(uri)
        out.append(
            {
                "name": a.get("nome") or "",
                "kind": a.get("tipo") or "",
                "external_id": _to_int(m.group(1)) if m else None,
                "party": None,
                "state": None,
                "gender": None,
                "order": i,
            }
        )
    return out


def enrich_camara_author(author: dict, deputy: dict) -> dict:
    """Preenche sexo/partido/UF de um autor da Câmara com o detalhe do deputado."""
    status = deputy.get("ultimoStatus", {}) or {}
    author["gender"] = _map_gender(deputy.get("sexo"))
    author["party"] = status.get("siglaPartido")
    author["state"] = status.get("siglaUf")
    return author


# ── Senado ───────────────────────────────────────────────────────────────────

def map_senado_proposition(
    summary: dict, detail: dict, full_text_url: str | None = None
) -> dict:
    """summary (lista tramitando) + detail (/materia/{id}) → kwargs de Proposition."""
    ident = summary.get("IdentificacaoMateria", {}) or {}
    dados = detail.get("DadosBasicosMateria", {}) or detail
    external_id = _to_int(ident.get("CodigoMateria") or summary.get("CodigoMateria"))
    sigla = ident.get("SiglaSubtipoMateria") or ""
    numero = _to_int(ident.get("NumeroMateria")) or 0
    ano = _to_int(ident.get("AnoMateria")) or 0

    return {
        "house": House.SENADO,
        "external_id": external_id,
        "type_code": sigla,
        "number_label": ident.get("DescricaoIdentificacaoMateria") or f"{sigla} {numero}/{ano}".strip(),
        "number": numero,
        "year": ano,
        "presented_at": _parse_date(dados.get("DataApresentacao") or summary.get("DataApresentacao")),
        "ementa": summary.get("Ementa") or dados.get("EmentaMateria") or "",
        "keywords": dados.get("IndexacaoMateria"),
        "full_text_url": full_text_url,
        "tramitation_url": f"https://www25.senado.leg.br/web/atividade/materias/-/materia/{external_id}",
        "raw_payload": {**detail, "_senado_process_id": ident.get("IdentificacaoProcesso")},
    }


# Tipos de texto derivados (não são o inteiro teor original da proposição).
_DERIVATIVE_TEXT = ("relat", "parecer", "emenda", "voto", "redaç", "substitut", "errata")


def pick_senado_full_text_url(texts: list[dict]) -> str | None:
    """Escolhe a URL do inteiro teor entre os documentos da matéria.

    Prioriza PDFs não-derivados (o texto inicial da proposição) e, entre eles,
    o mais antigo (apresentação). Equivale ao ``urlInteiroTeor`` da Câmara.
    """
    pdfs = [
        t
        for t in texts
        if t.get("UrlTexto")
        and (t.get("FormatoTexto") == "application/pdf" or t.get("TipoDocumento") == "PDF")
    ]
    if not pdfs:
        return None

    def _rank(t: dict) -> tuple[bool, str]:
        desc = (t.get("DescricaoTipoTexto") or "").lower()
        is_derivative = any(k in desc for k in _DERIVATIVE_TEXT)
        return (is_derivative, t.get("DataTexto") or "")

    return sorted(pdfs, key=_rank)[0]["UrlTexto"]


def _first(value):
    """Senado retorna objeto único ou lista; normaliza para o primeiro item."""
    if isinstance(value, list):
        return value[0] if value else {}
    return value or {}


def map_senado_event(movements: dict) -> dict | None:
    """Situação atual da matéria → kwargs de PropositionEvent.

    Caminho real: Materia.Autuacoes.Autuacao[0].SituacoesAtuais.SituacaoAtual[0].
    """
    materia = movements.get("Materia", {}) or {}
    autuacao = _first((materia.get("Autuacoes", {}) or {}).get("Autuacao"))
    situacao = _first((autuacao.get("SituacoesAtuais", {}) or {}).get("SituacaoAtual"))
    desc = situacao.get("DescricaoSituacao")
    if not desc:
        return None
    event_at = _parse_datetime(situacao.get("DataSituacao")) or timezone.now()
    return {
        "source_event_id": _source_id("senado-status", situacao.get("CodigoSituacao"), situacao),
        "source_kind": "status",
        "event_at": event_at,
        "title": desc,
        "description": desc,
        "situation": desc,
        "raw_payload": situacao,
    }


def map_senado_process_events(process: dict) -> list[dict]:
    """Normaliza informes legislativos do serviço atual de processos do Senado.

    Cada informe possui identificador próprio e é a unidade mais detalhada de
    movimentação. As situações continuam no payload para contexto, mas não são
    gravadas em paralelo para não duplicar a mesma alteração na celeridade.
    """
    situation_titles = {}
    for autuacao in process.get("autuacoes", []) or []:
        for situation in autuacao.get("situacoes", []) or []:
            situation_titles[situation.get("idTipo")] = situation.get("descricao")

    events = []
    for autuacao in process.get("autuacoes", []) or []:
        for report in autuacao.get("informesLegislativos", []) or []:
            event_at = _parse_datetime(report.get("data"))
            report_id = report.get("id")
            if not event_at or report_id is None:
                continue
            committee = report.get("colegiado", {}) or {}
            entity = report.get("enteAdministrativo", {}) or {}
            situation_id = report.get("idSituacaoIniciada")
            title = situation_titles.get(situation_id) or report.get("siglaSituacaoIniciada")
            events.append(
                {
                    "source_event_id": f"senado-informe:{report_id}",
                    "source_kind": "legislative_report",
                    "event_at": event_at,
                    "title": title or "Movimentação legislativa",
                    "description": report.get("descricao"),
                    "situation": title,
                    "committee_id": _to_int(committee.get("codigo")),
                    "committee_acronym": committee.get("sigla") or entity.get("sigla"),
                    "committee_name": committee.get("nome") or entity.get("nome"),
                    "raw_payload": report,
                }
            )
    return events


def _senado_current_situation(process: dict) -> dict:
    current_status = process.get("situacaoAtual")
    if not current_status:
        return {}
    normalized_status = " ".join(str(current_status).split()).casefold()
    for autuacao in process.get("autuacoes", []) or []:
        for situation in autuacao.get("situacoes", []) or []:
            description = " ".join(str(situation.get("descricao") or "").split()).casefold()
            if description == normalized_status:
                return situation
    return {}


def map_senado_process_status(process: dict) -> dict:
    """Campos atuais da matéria expostos pelo serviço substituto do Senado."""
    situation = _senado_current_situation(process)
    return {
        "current_status": process.get("situacaoAtual"),
        "current_status_code": _to_int(situation.get("idTipo")),
        "is_active": process.get("tramitando") != "Não",
    }


def map_senado_enactment(process: dict) -> dict | None:
    """Extract confirmed enactment metadata from the official Senado process."""
    situation = _senado_current_situation(process)
    status_code = _to_int(situation.get("idTipo"))
    if status_code not in _SENADO_ENACTED_STATUS_CODES:
        return None

    reports = []
    for autuacao in process.get("autuacoes", []) or []:
        for report in autuacao.get("informesLegislativos", []) or []:
            if _to_int(report.get("idSituacaoIniciada")) == status_code:
                reports.append(report)
    if not reports:
        return None

    report = max(reports, key=lambda item: item.get("data") or "")
    return _law_metadata(
        [report.get("descricao"), report.get("siglaSituacaoIniciada")],
        _parse_date(report.get("data")),
    )


def _source_id(prefix: str, source_id, payload: dict) -> str:
    if source_id not in (None, ""):
        return f"{prefix}:{source_id}"
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    return f"{prefix}:{sha256(serialized).hexdigest()[:24]}"


_SENADO_AUTHOR_RE = re.compile(r"^(.*?)\s*\(([^/]+)/([A-Z]{2})\)\s*$")
_SENADO_PERSON_PREFIX = re.compile(r"^(senador|senadora|deputad[oa])\s+", re.IGNORECASE)


def parse_senado_authors(detail: dict, summary: dict | None = None) -> list[dict]:
    """Normaliza o autor do Senado (string) em ``[{name, kind, party, state, ...}]``.

    O Senado expõe o autor como texto livre, ex.:
      "Senador Jader Barbalho (MDB/PA)"  ou  "Senado Federal - Comissão ..."
    """
    raw = (detail.get("DadosBasicosMateria", {}) or {}).get("Autor")
    if not raw and summary:
        raw = summary.get("Autor")
    raw = (raw or "").strip()
    if not raw:
        return []

    party = state = None
    name = raw
    m = _SENADO_AUTHOR_RE.match(raw)
    if m:
        name, party, state = m.group(1).strip(), m.group(2).strip(), m.group(3)

    is_person = bool(_SENADO_PERSON_PREFIX.match(name))
    clean_name = _SENADO_PERSON_PREFIX.sub("", name).strip() if is_person else name

    return [
        {
            "name": clean_name,
            "kind": "parlamentar" if is_person else "instituição",
            "party": party,
            "state": state,
            "gender": None,  # texto livre não traz sexo
            "external_id": None,  # nem código do parlamentar
            "order": 1,
        }
    ]


def parse_senado_authors_from_autoria(autores: list[dict]) -> list[dict]:
    """Normaliza autores via serviço de autoria do Senado.

    Mais rico que o texto livre: traz código, sexo, partido e UF
    (em ``IdentificacaoParlamentar``). Retorna ``[]`` se vazio (a task então
    cai no fallback ``parse_senado_authors``).
    """
    out = []
    for a in autores:
        ip = a.get("IdentificacaoParlamentar", {}) or {}
        name = ip.get("NomeParlamentar") or a.get("NomeAutor") or ""
        if not name.strip():
            continue
        is_person = bool(ip.get("CodigoParlamentar"))
        out.append(
            {
                "name": name.strip(),
                "kind": "parlamentar" if is_person else (a.get("DescricaoTipoAutor") or "instituição"),
                "party": ip.get("SiglaPartidoParlamentar"),
                "state": ip.get("UfParlamentar") or a.get("UfAutor"),
                "gender": _map_gender(ip.get("SexoParlamentar")),
                "external_id": _to_int(ip.get("CodigoParlamentar")),
                "order": _to_int(a.get("NumOrdemAutor")) or 1,
            }
        )
    return out
