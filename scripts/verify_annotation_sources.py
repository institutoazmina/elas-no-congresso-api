"""Verificação do de-para: resolve proposições da planilha de anotações via scraper.

Amostra N linhas aleatórias de annotated-data.csv e, para cada uma, tenta
resolver a proposição correta batendo nas APIs (via os clients de ingestion).
Valida cada candidato de id (coluna `uri` vs coluna `id`) contra a coluna `Nome`
(tipo+número/ano), já que a planilha é suja: às vezes `id` está errado, às vezes
`uri` aponta para o inteiro teor ou para a casa errada.

Uso:
    uv run python scripts/verify_annotation_sources.py [--n 12] [--seed 42] [--csv CAMINHO]

NÃO escreve no banco. Só coleta e imprime o de-para.
"""

import argparse
import csv
import os
import random
import re
import sys
from pathlib import Path

import django

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from apps.ingestion.clients.camara import CamaraClient  # noqa: E402
from apps.ingestion.clients.senado import SenadoClient  # noqa: E402

DEFAULT_CSV = Path(__file__).resolve().parent.parent / "tmp" / "annotated-data.csv"

# ── extração de id/casa das colunas sujas ────────────────────────────────────

_URI_PATTERNS = [
    (re.compile(r"propostas-legislativas/(\d+)"), "camara"),
    (re.compile(r"idProposicao=(\d+)"), "camara"),
    (re.compile(r"dadosabertos\.camara\.leg\.br/api/v2/proposicoes/(\d+)"), "camara"),
    (re.compile(r"camara\.leg\.br/.*proposicoes/(\d+)"), "camara"),
    (re.compile(r"senado\.leg\.br/.*/materia/(\d+)"), "senado"),
    (re.compile(r"legis\.senado\.leg\.br/dadosabertos/materia/(\d+)"), "senado"),
]

_CASA_TO_HOUSE = {"CD": "camara", "SF": "senado"}

# "PDL 24/2024" | "PL 5799/2019" | "PEC 49/2023"
_NOME_RE = re.compile(r"^\s*([A-Za-zÀ-ÿ]+)\s*0*(\d+)\s*/\s*(\d{4})")


def parse_nome(nome: str):
    m = _NOME_RE.match(nome or "")
    if not m:
        return None
    return (m.group(1).upper(), int(m.group(2)), int(m.group(3)))


def uri_candidate(uri: str):
    """(house, external_id) a partir do uri, ou None se não houver id de proposição."""
    for rgx, house in _URI_PATTERNS:
        m = rgx.search(uri or "")
        if m:
            return house, int(m.group(1))
    return None


def id_candidate(row):
    house = _CASA_TO_HOUSE.get((row.get("casa") or "").strip())
    raw = (row.get("id") or "").strip()
    if house and raw.isdigit():
        return house, int(raw)
    return None


def candidates(row):
    """Candidatos (house, id, origem) sem duplicatas, uri primeiro."""
    seen, out = set(), []
    for origem, cand in (("uri", uri_candidate(row.get("uri", ""))),
                         ("id", id_candidate(row))):
        if cand and cand not in seen:
            seen.add(cand)
            out.append((cand[0], cand[1], origem))
    return out


# ── coleta + normalização mínima para validação ──────────────────────────────

def fetch_camara(client, pid):
    d = client.fetch_detail(pid)
    if not d:
        return None
    return {
        "tipo": (d.get("siglaTipo") or "").upper(),
        "numero": _int(d.get("numero")),
        "ano": _int(d.get("ano")),
        "ementa": d.get("ementa"),
        "presented_at": d.get("dataApresentacao"),
        "full_text_url": d.get("urlInteiroTeor"),
        "n_authors": len(client.fetch_authors(pid)),
    }


def fetch_senado(client, mid):
    d = client.fetch_detail(mid)
    ident = (d.get("IdentificacaoMateria") or {}) if d else {}
    if not ident:
        return None
    dados = d.get("DadosBasicosMateria", {}) or {}
    return {
        "tipo": (ident.get("SiglaSubtipoMateria") or "").upper(),
        "numero": _int(ident.get("NumeroMateria")),
        "ano": _int(ident.get("AnoMateria")),
        "ementa": dados.get("EmentaMateria"),
        "presented_at": dados.get("DataApresentacao"),
        "n_authors": len(client.fetch_authors(mid)),
    }


def _int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def matches(expected, got):
    if not expected or not got:
        return False
    return expected == (got["tipo"], got["numero"], got["ano"])


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    args = ap.parse_args()

    with open(args.csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    rnd = random.Random(args.seed)
    sample = rnd.sample(rows, args.n)

    cam = CamaraClient()
    sen = SenadoClient()
    stats = {"resolvido": 0, "uri_venceu": 0, "id_venceu": 0, "sem_match": 0}

    try:
        for i, row in enumerate(sample, 1):
            nome = row.get("Nome", "")
            expected = parse_nome(nome)
            print(f"\n[{i}] casa={row['casa']!r} id={row['id']!r} Nome={nome!r}")
            print(f"    uri={row.get('uri','')[:70]!r}")
            print(f"    esperado (Nome): {expected}")

            resolved = None
            for house, pid, origem in candidates(row):
                got = fetch_camara(cam, pid) if house == "camara" else fetch_senado(sen, pid)
                ok = matches(expected, got)
                flag = "✓ MATCH" if ok else ("· não bate" if got else "· sem dados")
                got_str = f"{got['tipo']} {got['numero']}/{got['ano']}" if got else "—"
                print(f"      [{origem:3}] {house}/{pid} -> {got_str:20} {flag}")
                if ok and not resolved:
                    resolved = (house, pid, origem, got)

            if resolved:
                stats["resolvido"] += 1
                stats[f"{resolved[2]}_venceu"] += 1
                got = resolved[3]
                print(f"    ✅ RESOLVIDO por '{resolved[2]}' -> {resolved[0]}/{resolved[1]}")
                print(f"       ementa: {(got.get('ementa') or '')[:70]!r}")
                print(f"       presented_at={got.get('presented_at')} | autores={got.get('n_authors')}")
            else:
                stats["sem_match"] += 1
                print("    ❌ NENHUM candidato bateu com o Nome")
    finally:
        cam.close()
        sen.close()

    print(f"\n==== resumo (n={args.n}, seed={args.seed}) ====")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
