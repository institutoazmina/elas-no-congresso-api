"""Reconcilia proposition_annotations x annotated-data.csv, linha a linha.

SOMENTE LEITURA. Casa cada linha do CSV com a proposição do banco por
(type_code, number, year) — extraídos do `Nome` da planilha — sem bater na API.

Diz exatamente QUAIS anotações faltam e QUAIS sobram, por (proposição, avaliadora).
Contexto: a carga foi feita com retomadas manuais (--start) e a tabela não tem
unique constraint, então dá para perder e duplicar ao mesmo tempo — o saldo
líquido (-4) esconde as duas coisas.

Uso:
    docker exec <web> python scripts/reconcile_annotations.py
"""

import csv
import os
import re
import sys
from collections import Counter
from pathlib import Path

import django

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from django.db.models import Count  # noqa: E402
from django.db.models.functions import TruncHour  # noqa: E402

from apps.propositions.models import PropositionAnnotation  # noqa: E402

CSV_PATH = Path(__file__).resolve().parent.parent / "tmp" / "annotated-data.csv"

# Aceita '/', '-' e '.' como separador (a planilha tem 'PL 258-2019').
_NOME_RE = re.compile(r"^\s*([A-Za-zÀ-ÿ]+)\s*0*(\d+)\s*[/\-.]\s*(\d{4})")


def parse_nome(nome):
    m = _NOME_RE.match(nome or "")
    return (m.group(1).upper(), int(m.group(2)), int(m.group(3))) if m else None


def main():
    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    csv_c, sem_parse = Counter(), []
    for i, r in enumerate(rows, 1):
        p = parse_nome(r.get("Nome"))
        if not p:
            sem_parse.append((i, r.get("Nome")))
            continue
        csv_c[(*p, r["Avaliadora"].strip())] += 1

    db_c = Counter()
    for a in PropositionAnnotation.objects.values(
        "proposition__type_code", "proposition__number",
        "proposition__year", "organization__name",
    ):
        db_c[(
            (a["proposition__type_code"] or "").upper(),
            a["proposition__number"], a["proposition__year"],
            a["organization__name"],
        )] += 1

    print(f"CSV  : {sum(csv_c.values()) + len(sem_parse)} linhas")
    print(f"BANCO: {sum(db_c.values())} anotações")
    print(f"SALDO: {sum(db_c.values()) - sum(csv_c.values()) - len(sem_parse)}\n")

    if sem_parse:
        print("=== linhas cujo `Nome` não parseia (nunca resolvem) ===")
        for i, nome in sem_parse:
            print(f"  linha {i}: {nome!r}")
        print()

    faltando = {k: csv_c[k] - db_c.get(k, 0) for k in csv_c if csv_c[k] > db_c.get(k, 0)}
    sobrando = {k: db_c[k] - csv_c.get(k, 0) for k in db_c if db_c[k] > csv_c.get(k, 0)}

    print("=== FALTANDO no banco (csv > banco) ===")
    for k, n in sorted(faltando.items(), key=lambda x: -x[1]):
        tipo, num, ano, org = k
        print(f"  -{n}  {tipo} {num}/{ano}  ({csv_c[k]} no csv, {db_c.get(k, 0)} no banco)  {org}")
    print(f"  subtotal: {sum(faltando.values())}")

    print("\n=== SOBRANDO no banco (banco > csv) ===")
    for k, n in sorted(sobrando.items(), key=lambda x: -x[1]):
        tipo, num, ano, org = k
        print(f"  +{n}  {tipo} {num}/{ano}  ({csv_c.get(k, 0)} no csv, {db_c[k]} no banco)  {org}")
    print(f"  subtotal: {sum(sobrando.values())}")

    print("\n=== anotações por hora de created_at (separa os disparos) ===")
    for r in (
        PropositionAnnotation.objects.annotate(h=TruncHour("created_at"))
        .values("h").annotate(n=Count("id")).order_by("h")
    ):
        print(f"  {r['h']}  {r['n']:5d}")


if __name__ == "__main__":
    main()
