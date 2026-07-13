"""Carga retroativa da planilha de anotações humanas (annotated-data.csv).

Popula o banco (vazio) a partir da planilha, usando os MESMOS clients/mappers/
resolvers da coleta diária (apps.ingestion) — nada de lógica paralela:

  1. propositions        — coletadas via API (Câmara/Senado) a partir do `uri`
  2. parliamentarians     ┐ criados por resolve_author dentro de _persist
  3. proposition_authors  ┘ (mesma via da coleta diária)
  4. assessment_organizations — uma por "Avaliadora"
  5. proposition_annotations  — UMA por LINHA da planilha (mantém 3.989 linhas)

Resolução do id da proposição (a planilha é suja), em 3 caminhos, nesta ordem:
  1. id extraído da coluna `uri`;
  2. busca por `Nome` (tipo/número/ano) na API — resolve linhas cujo `uri` é só
     o inteiro teor (prop_mostrarintegra) e cujo `id` já não existe (404);
  3. id da coluna `id` (por último: pode dar 404 com retries lentos).
  Cada candidato é validado contra `Nome` (tipo+número/ano); só o que bate é aceito.
  Ver scripts/verify_annotation_sources.py e o teste --limit 50 (50/50 resolvidas).

Durabilidade (grava uma a uma — nada acumulado em memória):
  - propositions/authors/parliamentarians/parties: gravadas A CADA proposição
    (``_persist`` + ``update_or_create``).
  - cada anotação é gravada IMEDIATAMENTE após montada (uma linha = um INSERT
    commitado). Se cair, perde-se no máximo a linha em andamento.
  - ``--start N`` retoma de onde parou (pula as N primeiras linhas, sem apagar).

Uso:
    uv run python scripts/load_annotations.py [--limit N] [--dry-run] [--reset]
        [--start N] [--skip-deputy-enrich]

--limit N            processa só as N primeiras linhas (teste).
--dry-run            resolve/coleta e imprime, sem escrever no banco.
--reset              apaga proposition_annotations antes de carregar (recomeço limpo).
--start N            retoma a partir da linha N (pula as N primeiras; não apaga).
--skip-deputy-enrich não busca sexo/partido/UF do deputado (mais rápido, menos rico).
"""

import argparse
import csv
import logging
import os
import re
import sys
from pathlib import Path

import django

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from apps.core.enums import HumanRelevance  # noqa: E402
from apps.ingestion.clients.camara import CamaraClient  # noqa: E402
from apps.ingestion.clients.senado import SenadoClient  # noqa: E402
from apps.ingestion.fulltext import extract_pdf_text  # noqa: E402
from apps.ingestion.mappers import (  # noqa: E402
    enrich_camara_author,
    map_camara_event,
    map_camara_proposition,
    map_senado_event,
    map_senado_proposition,
    parse_camara_authors,
    parse_senado_authors,
    parse_senado_authors_from_autoria,
    pick_senado_full_text_url,
)
from apps.ingestion.tasks import _persist  # noqa: E402
from apps.propositions.models import (  # noqa: E402
    AssessmentOrganization,
    PropositionAnnotation,
)

logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("load_annotations")
logging.basicConfig(level=logging.INFO, format="%(message)s")

DEFAULT_CSV = Path(__file__).resolve().parent.parent / "annotated-data.csv"


# ── resolução do id da proposição (mesma lógica do verify) ────────────────────

_URI_PATTERNS = [
    (re.compile(r"propostas-legislativas/(\d+)"), "camara"),
    (re.compile(r"idProposicao=(\d+)"), "camara"),
    (re.compile(r"dadosabertos\.camara\.leg\.br/api/v2/proposicoes/(\d+)"), "camara"),
    (re.compile(r"camara\.leg\.br/.*proposicoes/(\d+)"), "camara"),
    (re.compile(r"senado\.leg\.br/.*/materia/(\d+)"), "senado"),
    (re.compile(r"legis\.senado\.leg\.br/dadosabertos/materia/(\d+)"), "senado"),
]
_CASA_TO_HOUSE = {"CD": "camara", "SF": "senado"}
_NOME_RE = re.compile(r"^\s*([A-Za-zÀ-ÿ]+)\s*0*(\d+)\s*/\s*(\d{4})")


def parse_nome(nome: str):
    m = _NOME_RE.match(nome or "")
    return (m.group(1).upper(), int(m.group(2)), int(m.group(3))) if m else None


def _int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _matches(expected, tipo, numero, ano):
    return bool(expected) and expected == ((tipo or "").upper(), _int(numero), _int(ano))


def _uri_candidate(row):
    for rgx, house in _URI_PATTERNS:
        m = rgx.search(row.get("uri") or "")
        if m:
            return (house, int(m.group(1)))
    return None


def _id_candidate(row):
    house = _CASA_TO_HOUSE.get((row.get("casa") or "").strip())
    raw = (row.get("id") or "").strip()
    return (house, int(raw)) if house and raw.isdigit() else None


def _search_candidate(row, expected, cam, sen):
    """3º caminho: busca por Nome (tipo/número/ano) na API. Resolve linhas cujo
    `uri` é só o inteiro teor e cujo `id` já não existe (404)."""
    if not expected:
        return None
    tipo, num, ano = expected
    hint = _CASA_TO_HOUSE.get((row.get("casa") or "").strip())
    houses = ([hint] + [h for h in ("camara", "senado") if h != hint]) if hint else ["camara", "senado"]
    for house in houses:
        try:
            if house == "camara":
                dados = cam.get_json(
                    "/proposicoes", params={"siglaTipo": tipo, "numero": num, "ano": ano}
                ).get("dados", [])
                for d in dados:
                    if _matches(expected, d.get("siglaTipo"), d.get("numero"), d.get("ano")):
                        return ("camara", _int(d["id"]))
            else:
                js = sen.get_json(
                    "/materia/pesquisa/lista", params={"sigla": tipo, "numero": num, "ano": ano}
                )
                mats = (js.get("PesquisaBasicaMateria", {}) or {}).get("Materias", {}).get("Materia", [])
                if isinstance(mats, dict):
                    mats = [mats]
                for m in mats:
                    if _matches(expected, m.get("Sigla"), m.get("Numero"), m.get("Ano")):
                        return ("senado", _int(m["Codigo"]))
        except Exception:
            log.debug("busca %s %s falhou", house, expected, exc_info=True)
    return None


# ── coleta + persistência de uma proposição (reusa _persist) ──────────────────

def _collect(house, pid, expected, cam, sen, enrich_deputy):
    """Coleta e valida contra `expected`. Retorna (prop_kwargs, event, authors) ou None."""
    if house == "camara":
        detail = cam.fetch_detail(pid)
        if not detail or not _matches(
            expected, detail.get("siglaTipo"), detail.get("numero"), detail.get("ano")
        ):
            return None
        authors = parse_camara_authors(cam.fetch_authors(pid))
        if enrich_deputy:
            for a in authors:
                if a["external_id"]:
                    enrich_camara_author(a, cam.fetch_deputy(a["external_id"]))
        return map_camara_proposition({"id": pid}, detail), map_camara_event(detail), authors

    materia = sen.fetch_detail(pid)
    ident = (materia.get("IdentificacaoMateria") or {}) if materia else {}
    if not ident or not _matches(
        expected, ident.get("SiglaSubtipoMateria"),
        ident.get("NumeroMateria"), ident.get("AnoMateria"),
    ):
        return None
    full_text_url = pick_senado_full_text_url(sen.fetch_texts(pid))
    authors = parse_senado_authors_from_autoria(
        sen.fetch_authors(pid)
    ) or parse_senado_authors(materia, materia)
    prop_kwargs = map_senado_proposition(materia, materia, full_text_url)
    return prop_kwargs, map_senado_event(sen.fetch_movements(pid)), authors


def resolve_and_persist(row, cam, sen, *, dry_run, enrich_deputy):
    """Resolve o candidato correto, coleta e persiste. Retorna pk (ou None).

    Ordem (lazy): uri → busca por Nome → id da coluna. A busca só é feita se o
    `uri` não resolver, e o `id` (que pode dar 404 lento) fica por último.
    """
    expected = parse_nome(row.get("Nome", ""))

    def _candidates():
        if (u := _uri_candidate(row)):
            yield u
        if (s := _search_candidate(row, expected, cam, sen)):
            yield s
        if (i := _id_candidate(row)):
            yield i

    seen = set()
    for house, pid in _candidates():
        if (house, pid) in seen:
            continue
        seen.add((house, pid))
        try:
            collected = _collect(house, pid, expected, cam, sen, enrich_deputy)
        except Exception:
            log.debug("coleta %s/%s falhou", house, pid, exc_info=True)
            continue
        if not collected:
            continue
        prop_kwargs, event_kwargs, authors = collected
        if dry_run:
            log.info("   [dry-run] %s/%s -> %s | autores=%d",
                     house, pid, prop_kwargs["number_label"], len(authors))
            return -1
        # Inteiro teor: baixa o PDF e extrai o texto (pypdf). None em falha.
        prop_kwargs["full_text"] = extract_pdf_text(prop_kwargs.get("full_text_url"))
        return _persist(prop_kwargs, event_kwargs, authors, [])
    return None


# ── mapeamento dos campos de anotação ─────────────────────────────────────────

_RELEVANCE_VALID = {c.value for c in HumanRelevance}


def map_is_favorable(v):
    v = (v or "").strip()
    if v == "Favorável":
        return True
    if v == "Desfavorável":
        return False
    return None  # vazio -> NULL (revisão manual no admin)


def map_relevance(v):
    """Relevância nunca é nula: vazio ou valor não reconhecido vira 'relevante'."""
    n = "_".join((v or "").strip().lower().split())
    return n if n in _RELEVANCE_VALID else HumanRelevance.RELEVANTE.value


def map_score(v):
    v = (v or "").strip().replace(",", ".")
    if not v:
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def clean(v):
    v = (v or "").strip()
    return v or None


def build_annotation(row, prop_pk, org):
    return PropositionAnnotation(
        proposition_id=prop_pk,
        organization=org,
        is_favorable=map_is_favorable(row.get("Avaliação")),
        has_caveats=(row.get("Há ressalvas?") or "").strip().upper() == "S",
        relevance=map_relevance(row.get("Relevância")),
        assessment_score=map_score(row.get("nota av")),
        relevance_score=map_score(row.get("nota rel")),
        human_theme=clean(row.get("Tema (class humana)")),
        comments=clean(row.get("Comentários")),
    )


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--start", type=int, default=0,
                    help="retoma a partir da linha N (pula as N primeiras; não apaga)")
    ap.add_argument("--skip-deputy-enrich", action="store_true")
    args = ap.parse_args()

    with open(args.csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if args.limit:
        rows = rows[: args.limit]
    log.info("Linhas a processar: %d", len(rows))

    if args.reset and not args.dry_run:
        n = PropositionAnnotation.objects.count()
        PropositionAnnotation.objects.all().delete()
        log.info("--reset: %d anotações apagadas", n)
    elif not args.dry_run and not args.start and PropositionAnnotation.objects.exists():
        log.error("Já existem anotações. Use --reset (recomeço limpo) "
                  "ou --start N (retomar a partir da linha N).")
        sys.exit(1)
    if args.start:
        log.info("--start: pulando as %d primeiras linhas (retomada)", args.start)

    cam, sen = CamaraClient(), SenadoClient()
    prop_cache: dict[tuple, int | None] = {}
    org_cache: dict[str, AssessmentOrganization] = {}
    stats = {"linhas": 0, "prop_ok": 0, "prop_falha": 0, "anot_criadas": 0}

    try:
        for i, row in enumerate(rows, 1):
            if i <= args.start:
                continue
            stats["linhas"] += 1
            key = (row.get("casa"), row.get("id"), row.get("uri"))
            if key not in prop_cache:
                try:
                    prop_cache[key] = resolve_and_persist(
                        row, cam, sen, dry_run=args.dry_run,
                        enrich_deputy=not args.skip_deputy_enrich,
                    )
                except Exception:
                    log.exception("Falha ao coletar linha %d (%s)", i, row.get("Nome"))
                    prop_cache[key] = None
                if prop_cache[key] is None:
                    log.warning("   NÃO RESOLVIDA: casa=%s id=%s Nome=%s uri=%s",
                                row.get("casa"), row.get("id"), row.get("Nome"),
                                (row.get("uri") or "")[:60])
            pk = prop_cache[key]
            if pk is None:
                stats["prop_falha"] += 1
                continue
            stats["prop_ok"] += 1

            if args.dry_run:
                continue

            name = row["Avaliadora"].strip()
            org = org_cache.get(name)
            if org is None:
                org, _ = AssessmentOrganization.objects.get_or_create(name=name)
                org_cache[name] = org
            # Grava a anotação JÁ — 1 INSERT commitado por linha (durável).
            build_annotation(row, pk, org).save()
            stats["anot_criadas"] += 1

            if i % 200 == 0:
                log.info("  ... linha %d/%d | anotações salvas=%d | props únicas=%d",
                         i, len(rows), stats["anot_criadas"], len(prop_cache))
    finally:
        cam.close()
        sen.close()

    log.info("\n==== resumo ====")
    for k, v in stats.items():
        log.info("  %s: %s", k, v)
    log.info("  proposições únicas resolvidas: %d",
             sum(1 for v in prop_cache.values() if v))
    log.info("  avaliadoras (orgs): %d", len(org_cache))


if __name__ == "__main__":
    main()
