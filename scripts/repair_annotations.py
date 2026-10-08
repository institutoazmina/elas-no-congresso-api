"""Reparo pontual de proposition_annotations contra annotated-data.csv.

A carga de prod ficou com saldo -4, que escondia DUAS falhas opostas:
  * 11 anotações FALTANDO (9 falhas transitórias de API + 1 regex de `Nome`
    + 1 typo de ano na planilha);
  * 7 anotações SOBRANDO (retomada com --start calculado a partir de
    "anotações salvas" em vez de "linhas processadas" → linhas reprocessadas,
    e sem unique constraint cada reprocesso vira INSERT novo).

Este script reconcilia o multiset (proposição, avaliadora, campos) CSV x banco:
  * SOBRANDO -> DELETE por pk explícita (apaga a cópia mais nova: maior id).
  * FALTANDO -> reusa resolve_and_persist/build_annotation do loader. NÃO dá
    para inserir via SQL puro: 10 das 11 proposições nem existem no banco
    (a resolução falhou, então _persist nunca rodou) e um INSERT cru deixaria
    ementa/presented_at/autores/full_text vazios.

Uso:
    python scripts/repair_annotations.py            # dry-run: mostra plano + SQL
    python scripts/repair_annotations.py --apply    # executa
"""

import argparse
import csv
import json
import logging
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import django

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from django.db import transaction  # noqa: E402
from django.db.models.signals import post_save  # noqa: E402

from apps.ingestion.clients.camara import CamaraClient  # noqa: E402
from apps.ingestion.clients.senado import SenadoClient  # noqa: E402
from apps.propositions.models import (  # noqa: E402
    AssessmentOrganization,
    Proposition,
    PropositionAnnotation,
)
from apps.propositions.signals import enqueue_match_on_save  # noqa: E402
from scripts.load_annotations import (  # noqa: E402
    build_annotation,
    clean,
    map_is_favorable,
    map_relevance,
    map_score,
    resolve_and_persist,
)

logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("repair")
logging.basicConfig(level=logging.INFO, format="%(message)s")

CSV_PATH = Path(__file__).resolve().parent.parent / "tmp" / "annotated-data.csv"
BACKUP = Path("/tmp/annotations_deleted_backup.json")

# Backfill histórico (PLs de 2019-2025 que já deviam estar no banco): o post_save
# de Proposition enfileira match_and_notify -> send_alert_email. Alerta de
# "proposição nova" sobre proposição velha seria errado, então o signal é
# desconectado — assim não há como disparar notificação, e nem broker é preciso.
post_save.disconnect(enqueue_match_on_save, sender=Proposition)

_NOME_RE = re.compile(r"^\s*([A-Za-zÀ-ÿ]+)\s*0*(\d+)\s*[/\-.]\s*(\d{4})")


def parse_nome(nome):
    m = _NOME_RE.match(nome or "")
    return (m.group(1).upper(), int(m.group(2)), int(m.group(3))) if m else None


def csv_fields(r):
    """Campos da anotação, pelos MESMOS mappers do loader."""
    return (
        map_is_favorable(r.get("Avaliação")),
        (r.get("Há ressalvas?") or "").strip().upper() == "S",
        map_relevance(r.get("Relevância")),
        map_score(r.get("nota av")),
        map_score(r.get("nota rel")),
        clean(r.get("Tema (class humana)")),
        clean(r.get("Comentários")),
    )


def db_fields(a):
    return (
        a.is_favorable, a.has_caveats, a.relevance,
        a.assessment_score, a.relevance_score, a.legacy_theme, a.comments,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="executa (sem isto é dry-run)")
    args = ap.parse_args()

    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    csv_c = Counter()
    csv_rows = defaultdict(list)
    for i, r in enumerate(rows, 1):
        p = parse_nome(r.get("Nome"))
        if not p:
            log.error("linha %d: `Nome` não parseia: %r — abortando", i, r.get("Nome"))
            sys.exit(1)
        k = (*p, r["Avaliadora"].strip(), *csv_fields(r))
        csv_c[k] += 1
        csv_rows[k].append((i, r))

    db_c = Counter()
    db_ids = defaultdict(list)
    for a in PropositionAnnotation.objects.select_related("proposition", "organization"):
        k = (
            (a.proposition.type_code or "").upper(), a.proposition.number,
            a.proposition.year, a.organization.name, *db_fields(a),
        )
        db_c[k] += 1
        db_ids[k].append(a.id)

    sobrando = {k: db_c[k] - csv_c.get(k, 0) for k in db_c if db_c[k] > csv_c.get(k, 0)}
    faltando = {k: csv_c[k] - db_c.get(k, 0) for k in csv_c if csv_c[k] > db_c.get(k, 0)}

    print(f"CSV  : {sum(csv_c.values())}")
    print(f"BANCO: {sum(db_c.values())}")
    print(f"a apagar : {sum(sobrando.values())}")
    print(f"a inserir: {sum(faltando.values())}")
    print(f"final previsto: {sum(db_c.values()) - sum(sobrando.values()) + sum(faltando.values())}\n")

    # ── DELETE: pk explícita, apaga as cópias mais novas ──────────────────
    to_delete = []
    for k, n in sobrando.items():
        ids = sorted(db_ids[k])[-n:]  # as n mais novas
        to_delete.extend(ids)
        print(f"  DELETE {n}x  {k[0]} {k[1]}/{k[2]}  {k[3]}  -> ids {ids}")

    if to_delete:
        print("\n--- SQL ---")
        print(f"DELETE FROM proposition_annotations WHERE id IN ({', '.join(map(str, sorted(to_delete)))});")

    print("\n--- a inserir (via loader: coleta a proposição se faltar) ---")
    for k, n in faltando.items():
        print(f"  INSERT {n}x  {k[0]} {k[1]}/{k[2]}  {k[3]}  (linha csv {csv_rows[k][0][0]})")

    if not args.apply:
        print("\n[dry-run] nada foi alterado. Use --apply para executar.")
        return

    # ── backup antes de apagar ────────────────────────────────────────────
    if to_delete:
        dump = list(
            PropositionAnnotation.objects.filter(id__in=to_delete)
            .values("id", "proposition_id", "organization_id", "is_favorable",
                    "has_caveats", "relevance", "assessment_score",
                    "relevance_score", "legacy_theme", "comments")
        )
        BACKUP.write_text(json.dumps(dump, indent=2, default=str), encoding="utf-8")
        print(f"\nbackup das {len(dump)} linhas -> {BACKUP}")
        with transaction.atomic():
            n, _ = PropositionAnnotation.objects.filter(id__in=to_delete).delete()
        print(f"apagadas: {n}")

    # ── inserts pelo caminho do loader ────────────────────────────────────
    cam, sen = CamaraClient(), SenadoClient()
    ok = falhou = 0
    try:
        for k, n in faltando.items():
            linha, r = csv_rows[k][0]
            pk = resolve_and_persist(r, cam, sen, dry_run=False, enrich_deputy=True)
            if pk is None:
                log.error("  linha %d: NÃO RESOLVEU %s %s/%s", linha, k[0], k[1], k[2])
                falhou += n
                continue
            org, _ = AssessmentOrganization.objects.get_or_create(name=k[3])
            for _ in range(n):
                build_annotation(r, pk, org).save()
                ok += 1
            print(f"  ok linha {linha}: {k[0]} {k[1]}/{k[2]} -> prop={pk} x{n}")
    finally:
        cam.close()
        sen.close()

    print(f"\ninseridas: {ok} | falharam: {falhou}")
    print(f"total agora: {PropositionAnnotation.objects.count()}")


if __name__ == "__main__":
    main()
