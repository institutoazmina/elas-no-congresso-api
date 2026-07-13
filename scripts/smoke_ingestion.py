"""Smoke test da coleta contra os endpoints REAIS (sem banco).

Usa os mesmos clients/mappers/theme_assert do app de ingestão para:
  1. bater nas APIs da Câmara e do Senado,
  2. rodar o filtro de tema antecipado,
  3. mapear o payload para os kwargs dos modelos,
  4. salvar fixtures reais em apps/ingestion/tests/fixtures/.

Uso:
    uv run python scripts/smoke_ingestion.py [--days N]

NÃO escreve no banco. Resolução de autores (que toca o DB) é validada
apenas na forma normalizada (parse_*_authors), não em resolve_author.
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import django

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from apps.ingestion.clients.camara import CamaraClient  # noqa: E402
from apps.ingestion.clients.senado import SenadoClient  # noqa: E402
from apps.ingestion.mappers import (  # noqa: E402
    map_camara_event,
    map_camara_proposition,
    map_senado_event,
    map_senado_proposition,
    parse_camara_authors,
    parse_senado_authors,
    pick_senado_full_text_url,
)
from apps.ingestion.theme_assert import assert_theme  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "apps/ingestion/tests/fixtures"


def _dump(name: str, data) -> None:
    path = FIXTURES / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    print(f"   fixture salva: {path.relative_to(Path.cwd())}")


def smoke_camara(window_days: int, max_relevant: int = 2) -> None:
    end = date.today() + timedelta(days=1)
    start = end - timedelta(days=window_days + 1)
    print(f"\n=== CÂMARA  janela {start} → {end} ===")

    fetched = relevant = 0
    saved = 0
    with CamaraClient() as client:
        for summary in client.list_propositions(start, end):
            fetched += 1
            if not assert_theme(summary.get("ementa"))["row_relevant"]:
                continue
            relevant += 1
            if saved == 0:
                _dump("camara_summary.json", summary)

            prop_id = int(summary["id"])
            detail = client.fetch_detail(prop_id)
            res = assert_theme(
                summary.get("ementa"), detail.get("ementaDetalhada"), detail.get("keywords")
            )
            if not res["row_relevant"]:
                continue
            authors_raw = client.fetch_authors(prop_id)
            authors = parse_camara_authors(authors_raw)
            prop = map_camara_proposition(summary, detail)
            event = map_camara_event(detail)

            print(f"\n  [{prop['number_label']}] id={prop_id}")
            print(f"    temas: {res['temas']}")
            print(f"    presented_at={prop['presented_at']} status={prop['current_status']!r}")
            print(f"    autores normalizados: {authors}")
            print(f"    event: {event['situation'] if event else None!r}")

            if saved == 0:
                _dump("camara_detail.json", detail)
                _dump("camara_authors.json", authors_raw)
                _dump("camara_mapped_proposition.json", prop)
            saved += 1
            if relevant >= max_relevant:
                break
    print(f"\n  Câmara: fetched={fetched} relevant>={relevant} (parou em {max_relevant})")


def smoke_senado(window_days: int, max_relevant: int = 2) -> None:
    print("\n=== SENADO ===")
    fetched = relevant = saved = 0
    with SenadoClient() as client:
        # Tenta alguns dias recentes até achar matérias tramitando.
        for back in range(1, window_days + 2):
            day = date.today() - timedelta(days=back)
            materias = list(client.list_materias(day))
            if not materias:
                continue
            print(f"  data {day}: {len(materias)} matérias em tramitação")
            if saved == 0:
                _dump("senado_summary.json", materias[0])

            for summary in materias:
                fetched += 1
                if not assert_theme(summary.get("Ementa"))["row_relevant"]:
                    continue
                relevant += 1
                ident = summary.get("IdentificacaoMateria", {}) or {}
                materia_id = int(ident.get("CodigoMateria") or summary["CodigoMateria"])
                detail = client.fetch_detail(materia_id)
                movements = client.fetch_movements(materia_id)
                texts = client.fetch_texts(materia_id)
                full_text_url = pick_senado_full_text_url(texts)
                authors = parse_senado_authors(detail, summary)
                prop = map_senado_proposition(summary, detail, full_text_url)
                event = map_senado_event(movements)

                print(f"\n  [{prop['number_label']}] id={materia_id}")
                print(f"    presented_at={prop['presented_at']} ementa={(prop['ementa'] or '')[:80]!r}")
                print(f"    autores normalizados: {authors}")
                print(f"    event: {event['situation'] if event else None!r}")
                print(f"    inteiro teor: {full_text_url}")

                if saved == 0:
                    _dump("senado_detail.json", detail)
                    _dump("senado_movements.json", movements)
                    _dump("senado_texts.json", texts)
                    _dump("senado_mapped_proposition.json", prop)
                saved += 1
                if relevant >= max_relevant:
                    break
            if relevant >= max_relevant or fetched:
                break
    print(f"\n  Senado: fetched={fetched} relevant>={relevant}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="tamanho da janela em dias")
    ap.add_argument("--skip-camara", action="store_true")
    ap.add_argument("--skip-senado", action="store_true")
    args = ap.parse_args()

    if not args.skip_camara:
        smoke_camara(args.days)
    if not args.skip_senado:
        smoke_senado(args.days)
    print("\nSmoke test concluído.")
