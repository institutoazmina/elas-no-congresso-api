"""Tradução dos payloads brutos das APIs para os campos dos modelos do domínio.

Substitui rename_cols_camara.py / rename_cols_senado.py / df_config.py do bot.
Cada ``map_*`` devolve dicts prontos para ``update_or_create``/``create``.
"""

import re
from datetime import date, datetime

from django.utils import timezone

from apps.core.enums import House

# ── helpers ──────────────────────────────────────────────────────────────────

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


# ── Câmara ───────────────────────────────────────────────────────────────────

def map_camara_proposition(summary: dict, detail: dict, themes: list[str]) -> dict:
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
        "raw_payload": {"summary": summary, "detail": detail, "themes": themes},
    }


def map_camara_event(detail: dict) -> dict | None:
    """Última movimentação (statusProposicao) → kwargs de PropositionEvent."""
    status = detail.get("statusProposicao", {}) or {}
    event_at = _parse_datetime(status.get("dataHora"))
    if not event_at:
        return None
    return {
        "event_at": event_at,
        "sequence": _to_int(status.get("sequencia")),
        "description": status.get("descricaoTramitacao"),
        "situation": status.get("descricaoSituacao"),
        "dispatch": status.get("despacho"),
        "raw_payload": status,
    }


def parse_camara_authors(authors: list[dict]) -> list[dict]:
    """Normaliza autores da Câmara em ``{name, kind, external_id, order}``."""
    out = []
    for i, a in enumerate(authors, start=1):
        uri = a.get("uri") or ""
        m = _DEPUTY_ID_RE.search(uri)
        out.append(
            {
                "name": a.get("nome") or "",
                "kind": a.get("tipo") or "",
                "external_id": _to_int(m.group(1)) if m else None,
                "order": i,
            }
        )
    return out


# ── Senado ───────────────────────────────────────────────────────────────────

def map_senado_proposition(
    summary: dict, detail: dict, themes: list[str], full_text_url: str | None = None
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
        "raw_payload": {"summary": summary, "detail": detail, "themes": themes},
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
        "event_at": event_at,
        "description": desc,
        "situation": desc,
        "raw_payload": situacao,
    }


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
            "external_id": None,  # não disponível no texto livre do Senado
            "order": 1,
        }
    ]
