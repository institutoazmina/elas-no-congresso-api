"""Filtro de relevância temática.

Decide se uma proposição é relevante ao tema gênero/direitos das mulheres,
rodando sobre a ementa e, quando necessário, sobre o inteiro teor.

Os termos são editáveis no admin (modelo ``RelevanceTerm``). Enquanto não houver
termos cadastrados, cai nos defaults do vocabulário,
atualizados por migração de dados.
"""

import re
import unicodedata
from functools import lru_cache

from django.core.cache import cache

from .relevance_defaults import DEFAULT_COMBINED, DEFAULT_STANDALONE

# Chave/TTL do cache da lista de termos (a regex compilada é memoizada em processo).
_CACHE_KEY = "ingestion:relevance_terms:v2"
_CACHE_TTL = 300  # segundos

# Aliases retained for callers; migrations keep their own frozen vocabulary.
_DEFAULT_STANDALONE = DEFAULT_STANDALONE
_DEFAULT_COMBINED = DEFAULT_COMBINED


def _phrase_pattern(term: str):
    # Whitespace in a PDF may include line/page breaks; never join separate fields.
    words = unicodedata.normalize("NFC", term).split()
    return re.compile(r"(?<!\w)" + r"\s+".join(map(re.escape, words)) + r"(?!\w)", re.I)


@lru_cache(maxsize=16)
def _compile(standalone: tuple, combined: tuple):
    rules = [(term, (_phrase_pattern(term),)) for term in standalone if term.strip()]
    for term in combined:
        # A spaced plus is an operator; the trailing plus in LGBTQIA+ is literal.
        parts = re.split(r"\s+\+\s+", term.strip())
        if len(parts) == 1:
            parts.append("MULHER")  # Compatibility with existing admin-created rules.
        if all(part.strip() for part in parts):
            rules.append((term, tuple(_phrase_pattern(part) for part in parts)))
    return tuple(rules)


def _active_terms() -> tuple[tuple, tuple]:
    """Lista de termos ativos (standalone, combined), do banco ou dos defaults.

    Cacheada (TTL curto + invalidação por signal ao salvar/excluir termos).
    """
    cached = cache.get(_CACHE_KEY)
    if cached is not None:
        return cached

    try:
        from .models import RelevanceTerm

        rows = list(RelevanceTerm.objects.filter(is_active=True).values_list("term", "mode"))
    except Exception:  # noqa: BLE001 — tabela ausente durante migração/bootstrap
        rows = []

    if rows:
        standalone = tuple(t for t, m in rows if m == "standalone")
        combined = tuple(t for t, m in rows if m == "combined")
    else:
        standalone, combined = tuple(_DEFAULT_STANDALONE), tuple(_DEFAULT_COMBINED)

    cached = (standalone, combined)
    cache.set(_CACHE_KEY, cached, _CACHE_TTL)
    return cached


def invalidate_cache() -> None:
    """Limpa o cache de termos (chamado pelo signal ao editar no admin)."""
    cache.delete(_CACHE_KEY)


def assert_theme(*fields: str | None) -> dict:
    """Avalia se os campos textuais dados são relevantes ao tema.

    Retorna ``{"row_relevant": bool, "temas": list[str]}``.
    """
    texts = [unicodedata.normalize("NFC", field) for field in fields if field]
    matches = [
        term
        for term, patterns in _compile(*_active_terms())
        if all(any(pattern.search(text) for text in texts) for pattern in patterns)
    ]
    return {"row_relevant": bool(matches), "temas": matches}
