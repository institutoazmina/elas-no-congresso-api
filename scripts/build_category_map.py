"""Gera ``tmp/categories-2026.csv`` a partir da planilha ``dataset-categories.csv``.

A planilha é o mesmo ``annotated-data.csv`` da carga acrescido da coluna
`Categorias 2026` — 31 colunas idênticas, 3988 linhas. Deste script sai só o
essencial para o backfill: uma linha por (proposição, avaliadora).

Duas correções aplicadas aqui, ambas verificadas contra o banco em produção:

  1. `PL 6410/2022` -> `PL 6410/2019`. A planilha de origem é ANTERIOR ao commit
     9c8041f: a matéria 140157 do Senado é a PL 6410/2019 (ementa confere:
     Lei 8.213, INSS) e PL 6410/2022 não existe. É a única linha das 3988 que,
     sem isto, não casa com o banco.

  2. `PL 1819/2019` da Themis aparece duas vezes com categorias diferentes
     ('Trabalho, Economia…' e 'Violências de Gênero') — único par ambíguo em
     3126. Fica a primeira ocorrência, e o script imprime o descarte.

Uso:
    uv run python scripts/build_category_map.py [--csv dataset-categories.csv]
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.propositions.categories import parse_category, parse_nome  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = ROOT / "dataset-categories.csv"
OUT = ROOT / "tmp" / "categories-2026.csv"

# Typo de ano na planilha de origem (ver docstring).
ALIAS = {("PL", 6410, 2022): ("PL", 6410, 2019)}


def build(csv_path: Path) -> tuple[list[dict], list[str]]:
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    mapa: dict[tuple, dict] = {}
    avisos: list[str] = []
    for i, r in enumerate(rows, 2):
        prop = parse_nome(r.get("Nome"))
        if not prop:
            avisos.append(f"linha {i}: `Nome` não parseia: {r.get('Nome')!r}")
            continue
        prop = ALIAS.get(prop, prop)
        category = parse_category(r.get("Categorias 2026"))
        if not category:
            avisos.append(f"linha {i}: categoria não reconhecida: {r.get('Categorias 2026')!r}")
            continue
        org = (r.get("Avaliadora") or "").strip()
        key = (*prop, org)
        if key in mapa:
            if mapa[key]["category"] != category:
                avisos.append(
                    f"linha {i}: {prop[0]} {prop[1]}/{prop[2]} · {org} já mapeada como "
                    f"{mapa[key]['category']!r}; descartando {category!r}"
                )
            continue
        mapa[key] = {
            "type_code": prop[0], "number": prop[1], "year": prop[2],
            "organization": org, "category": category,
        }
    return list(mapa.values()), avisos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    linhas, avisos = build(args.csv)
    linhas.sort(key=lambda d: (d["type_code"], d["year"], d["number"], d["organization"]))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["type_code", "number", "year", "organization", "category"])
        w.writeheader()
        w.writerows(linhas)

    print(f"{args.out.relative_to(ROOT)}: {len(linhas)} pares (proposição, avaliadora)")
    for a in avisos:
        print(f"  aviso: {a}")


if __name__ == "__main__":
    main()
