"""Reconcilia proposition_annotations (banco) x annotated-data.csv (planilha).

SOMENTE LEITURA — não escreve nada. Responde três perguntas:

  1. Quantas anotações faltam/sobram, POR AVALIADORA? (localiza o rombo sem
     precisar bater na API da Câmara/Senado: 'Avaliadora' -> organization.)
  2. Há duplicatas? A carga foi feita com retomadas manuais (--start) e a
     tabela não tem unique constraint: linha reprocessada = INSERT novo.
  3. Em que janela de created_at cada bloco entrou? (separa os disparos)

Uso (em prod):
    kamal app exec --reuse --roles web "python scripts/diagnose_annotations.py"
"""

import csv
import os
import sys
from collections import Counter
from pathlib import Path

import django

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from django.db.models import Count  # noqa: E402

from apps.propositions.models import PropositionAnnotation  # noqa: E402

CSV_PATH = Path(__file__).resolve().parent.parent / "tmp" / "annotated-data.csv"

# Campos que identificam uma anotação (tudo que build_annotation preenche).
_DUP_FIELDS = [
    "proposition_id", "organization__name", "is_favorable", "has_caveats",
    "relevance", "assessment_score", "relevance_score", "legacy_theme", "comments",
]


def main():
    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    csv_by_org = Counter(r["Avaliadora"].strip() for r in rows)
    db_by_org = Counter(
        {
            r["organization__name"]: r["n"]
            for r in PropositionAnnotation.objects.values("organization__name")
            .annotate(n=Count("id"))
        }
    )

    print(f"CSV  : {sum(csv_by_org.values())} linhas / {len(csv_by_org)} avaliadoras")
    print(f"BANCO: {sum(db_by_org.values())} anotações / {len(db_by_org)} organizações")
    print(f"SALDO: {sum(db_by_org.values()) - sum(csv_by_org.values())}\n")

    print("=== diferença por avaliadora (banco - csv) ===")
    perdidas = sobrando = 0
    for org in sorted(set(csv_by_org) | set(db_by_org)):
        esperado, real = csv_by_org.get(org, 0), db_by_org.get(org, 0)
        d = real - esperado
        if d:
            print(f"  {d:+5d}   esperado={esperado:5d} real={real:5d}  {org}")
            perdidas += -d if d < 0 else 0
            sobrando += d if d > 0 else 0
    if not (perdidas or sobrando):
        print("  (nenhuma — todas batem)")
    print(f"\n  faltando: {perdidas} | sobrando: {sobrando}")

    print("\n=== duplicatas exatas no banco ===")
    dups = (
        PropositionAnnotation.objects.values(*_DUP_FIELDS)
        .annotate(n=Count("id"))
        .filter(n__gt=1)
        .order_by("-n")
    )
    total_extra = sum(d["n"] - 1 for d in dups)
    print(f"  grupos duplicados: {dups.count()} | linhas excedentes: {total_extra}")
    for d in dups[:15]:
        print(f"    x{d['n']}  prop={d['proposition_id']}  {d['organization__name']}")

    print("\n=== anotações por dia/hora de created_at (separa os disparos) ===")
    for r in (
        PropositionAnnotation.objects.extra(
            select={"h": "date_trunc('hour', created_at)"}
        )
        .values("h")
        .annotate(n=Count("id"))
        .order_by("h")
    ):
        print(f"  {r['h']}  {r['n']:5d}")


if __name__ == "__main__":
    main()
