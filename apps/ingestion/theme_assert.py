"""Filtro de relevância temática.

Decide se uma proposição é relevante ao tema gênero/direitos das mulheres,
rodando sobre a ementa ANTES dos saltos caros (autores, inteiro teor).

Os termos são editáveis no admin (modelo ``RelevanceTerm``). Enquanto não houver
termos cadastrados, cai nos defaults abaixo (os mesmos do elasnocongressobot),
que também alimentam a migração de seed.
"""

import re
from functools import lru_cache

from django.core.cache import cache

# Chave/TTL do cache da lista de termos (a regex compilada é memoizada em processo).
_CACHE_KEY = "ingestion:relevance_terms"
_CACHE_TTL = 300  # segundos

# Termos relevantes por si só.
_DEFAULT_STANDALONE = [
    "ABORTAMENTO",
    "ABORTO",
    "ABUSO SEXUAL",
    "AMAMENTAÇÃO",
    "ASSÉDIO",
    "ASSÉDIO SEXUAL",
    "BEBÊ",
    "CASAMENTO",
    "CASAMENTO INFANTIL",
    "CONCEPÇÃO",
    "CONTRACEPÇÃO",
    "CONTRACEPTIVO",
    "CRECHE",
    "CRIANÇA",
    "CYTOTEC",
    "DIREITO À VIDA",
    "DIREITO DOS HOMENS",
    "DIREITO REPRODUTIVO",
    "DIREITOS REPRODUTIVOS",
    "DIVÓRCIO",
    "DOMÉSTICA",
    "EDUCAÇÃO DOMICILIAR",
    "EDUCAÇÃO INFANTIL",
    "EDUCAÇÃO SEXUAL",
    "ESCOLA SEM PARTIDO",
    "ESTUPRO",
    "ESTUPRO DE VULNERÁVEL",
    "EXPLORAÇÃO SEXUAL",
    "FEMINICÍDIO",
    "FEMININO",
    "FEMINISMO",
    "FETO",
    "GÊNERO",
    "GESTAÇÃO",
    "GESTANTE",
    "GRAVIDEZ",
    "GUARDA DE FILHOS",
    "GUARDA DOS FILHOS",
    "HOMESCHOOLING",
    "HOMICÍDIO DE MULHER",
    "HOMOSSEXUAL",
    "IDENTIDADE DE GÊNERO",
    "IDEOLOGIA DE GÊNERO",
    "IGUALDADE",
    "IGUALDADE DE GÊNERO",
    "INTERRUPÇÃO DA GESTAÇÃO",
    "INTERRUPÇÃO DA GRAVIDEZ",
    "LÉSBICA",
    "LICENÇA MATERNIDADE",
    "MACHISMO",
    "MÃE",
    "MARIA DA PENHA",
    "MATERNIDADE",
    "MIFEPRISTONE",
    "MISOPROSTOL",
    "MORTE DE MULHER",
    "MUDANÇA DE SEXO",
    "MULHER",
    "MULHER NEGRA",
    "MULHER TRANS",
    "MULHERES INDÍGENAS",
    "MULHERES NEGRAS",
    "MULHERES QUILOMBOLAS",
    "MULHERES TRANS",
    "NASCITURO",
    "NEGRA",
    "ORIENTAÇÃO SEXUAL",
    "PARTO",
    "PROSTITUIÇÃO",
    "READEQUAÇÃO SEXUAL",
    "SEXO",
    "SEXUALIDADE",
    "TRABALHO DOMÉSTICO",
    "TRANS",
    "TRANSEX",
    "TRANSGEN",
    "TRANSEXUAL",
    "TRANSEXUALIDADE",
    "ÚTERO",
    "VIOLÊNCIA CONTRA A MULHER",
    "VIOLÊNCIA DE GÊNERO",
    "VIOLÊNCIA POLÍTICA DE GÊNERO",
    "VIOLÊNCIA DOMÉSTICA",
    "VIOLÊNCIA OBSTÉTRICA",
    "VIOLÊNCIA SEXUAL",
    "SEXUAL",
]

# Termos relevantes só quando o texto também contém "mulher".
_DEFAULT_COMBINED = [
    "COTAS",
    "TRABALHO",
    "RAÇA",
    "PARTICIPAÇÃO POLÍTICA",
    "RACIAL",
    "POLÍTICA",
    "RACISMO",
    "RELIGIÃO",
    "EDUCAÇÃO RELIGIOSA",
    "DEUS",
]


@lru_cache(maxsize=16)
def _compile(standalone: tuple, combined: tuple):
    """Compila as duas regex a partir das tuplas de termos (memoizado)."""
    standalone_re = (
        re.compile(r"\b(" + "|".join(re.escape(t) for t in standalone) + r")\b", re.IGNORECASE)
        if standalone
        else None
    )
    combined_re = (
        re.compile(
            r"(?=.*\bmulher\b).*\b(" + "|".join(re.escape(t) for t in combined) + r")\b",
            re.IGNORECASE,
        )
        if combined
        else None
    )
    return standalone_re, combined_re


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
    text = " ".join(f or "" for f in fields)
    if not text.strip():
        return {"row_relevant": False, "temas": []}

    standalone_re, combined_re = _compile(*_active_terms())
    matches: list[str] = []
    if standalone_re:
        matches += standalone_re.findall(text)
    if combined_re:
        matches += combined_re.findall(text)
    return {"row_relevant": len(matches) > 0, "temas": matches}
