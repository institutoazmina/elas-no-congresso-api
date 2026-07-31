"""Mapa (proposição, avaliadora) -> Categorias 2026, usado no backfill.

Fonte: ``tmp/categories-2026.csv``, gerado por ``scripts/build_category_map.py``
a partir da planilha ``dataset-categories.csv``. O arquivo é versionado e entra
na imagem (``tmp/`` não está no .dockerignore), porque a migração
``0006_annotation_category_backfill`` o lê para preencher a coluna.

A chave é ``(type_code, number, year, organization)`` — o mesmo casamento por
`Nome` que ``load_annotations.py`` usa, e NÃO a coluna `id` da planilha, que tem
ids truncados (PDL 20/2024: 241912 na planilha, 2419012 no banco) e codteor no
lugar do id (PL 3598/2020).
"""

import csv
import re
import unicodedata
from pathlib import Path

from apps.core.enums import PropositionCategory

CATEGORY_MAP_PATH = Path(__file__).resolve().parent.parent.parent / "tmp" / "categories-2026.csv"

# Aceita '/', '-' e '.' como separador — a planilha tem 'PL 258-2019'.
NOME_RE = re.compile(r"^\s*([A-Za-zÀ-ÿ]+)\s*0*(\d+)\s*[/\-.]\s*(\d{4})")


def _fold(value: str) -> str:
    """Normaliza rótulo para comparação: sem acento, sem caixa, espaço colapsado."""
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", value).strip().lower()


_BY_LABEL = {_fold(label): value for value, label in PropositionCategory.choices}


def parse_category(raw: str | None) -> str | None:
    """Rótulo da planilha -> valor do enum. None se não reconhecido.

    Tolera divergência de caixa/acento, que existe no dado: a planilha traz uma
    linha 'Direitos sexuais e reprodutivos' entre 542 'Direitos Sexuais e
    Reprodutivos'.
    """
    folded = _fold(raw or "")
    if not folded:
        return None
    return _BY_LABEL.get(folded) or (folded if folded in PropositionCategory.values else None)


def parse_nome(nome: str | None) -> tuple[str, int, int] | None:
    m = NOME_RE.match(nome or "")
    return (m.group(1).upper(), int(m.group(2)), int(m.group(3))) if m else None


def load_category_map(path: Path | None = None) -> dict[tuple[str, int, int, str], str]:
    """Lê o CSV do mapa. Chave ``(type_code, number, year, organization)``."""
    path = path or CATEGORY_MAP_PATH
    with open(path, encoding="utf-8") as f:
        return {
            (r["type_code"].upper(), int(r["number"]), int(r["year"]), r["organization"]): r["category"]
            for r in csv.DictReader(f)
        }


def proposition_fallback(mapa: dict[tuple, str]) -> dict[tuple[str, int, int], str]:
    """Categoria por proposição, apenas onde ela é inequívoca entre as avaliadoras.

    A planilha de categorias divergiu do banco em três anotações: PL 797/2026 e
    PL 3596/2025 mudaram de avaliadora (Plan International -> Juristas Negras) e
    PL 5906/2023 · Themis é a linha que a planilha nova perdeu (3988 contra 3989).
    Nas três, a proposição tem categoria única, então casar por proposição é
    seguro.

    Proposições com categorias divergentes (7, quando avaliadoras discordam)
    ficam DE FORA de propósito: ali o backfill deve abortar em vez de escolher.
    """
    por_proposicao: dict[tuple[str, int, int], set[str]] = {}
    for (type_code, number, year, _org), category in mapa.items():
        por_proposicao.setdefault((type_code, number, year), set()).add(category)
    return {k: v.pop() for k, v in por_proposicao.items() if len(v) == 1}
