"""Endpoints de dataset para treinamento do modelo.

Reconstrói o dataset rotulado a partir do banco: uma linha por
(anotação humana × autor da proposição). Proposições com N coautores geram N
linhas — reproduzindo a estrutura do CSV de treino original.

- ``GET /dataset``           — JSON paginado (limit/offset).
- ``GET /dataset/download``  — baixa o dataset INTEIRO em csv | parquet | jsonl.

Por padrão retorna só dados anotados (``is_favorable`` preenchido);
``include_unlabeled=true`` inclui os sem rótulo. Campos em inglês; os rótulos de
``assessment``/``relevance``/``gender``/``theme`` saem em português (via Case/When
no SQL).

``theme`` mudou de conteúdo: era o texto livre da planilha (107 variantes, com
duplicatas de caixa) e passou a ser a categoria da taxonomia fechada
(``PropositionCategory``, 10 valores). O texto original continua disponível na
coluna ``legacy_theme``, acrescentada no fim para não deslocar as demais.
"""

import csv
import io
import json
import os

# pyarrow empacota o jemalloc, que segfaulta dentro do worker ASGID (uvicorn) —
# forçar o alocador do sistema. Precisa estar setado ANTES do 1º import de pyarrow.
os.environ.setdefault("ARROW_DEFAULT_MEMORY_POOL", "system")

from django.db.models import Case, CharField, F, Value, When
from django.db.models.functions import Coalesce
from django.http import HttpResponse, StreamingHttpResponse
from ninja import Field, Router, Schema
from ninja.errors import HttpError
from ninja.pagination import LimitOffsetPagination, paginate

from apps.core.enums import Gender, HumanRelevance, PropositionCategory

from .models import PropositionAnnotation

router = Router()

# Ordem canônica dos campos de saída (vale p/ JSON, CSV, Parquet e JSONL).
FIELDS = [
    "house", "id", "uri", "type_code", "name", "year", "summary", "full_text",
    "author", "author_index", "party", "state", "gender", "assessment",
    "relevance", "theme", "is_favorable", "legacy_theme",
]


class DatasetRowSchema(Schema):
    house: str
    id: int = Field(validation_alias="external_id")  # propositions.external_id
    uri: str | None = None
    type_code: str | None = None
    name: str | None = None
    year: int | None = None
    summary: str | None = None  # propositions.ementa
    full_text: str | None = None
    author: str | None = None
    author_index: int | None = None  # proposition_authors.order_index
    party: str | None = None
    state: str | None = None
    gender: str | None = None
    assessment: str | None = None
    relevance: str | None = Field(default=None, validation_alias="relevance_label")
    theme: str | None = Field(default=None, validation_alias="theme_label")
    is_favorable: bool | None = None
    legacy_theme: str | None = None


def _label_case(field: str, mapping: dict) -> Case:
    """Mapeia o valor cru de ``field`` para o rótulo em português (via SQL)."""
    return Case(
        *[When(**{field: k}, then=Value(v)) for k, v in mapping.items()],
        default=Value(None),
        output_field=CharField(),
    )


def _dataset_qs(house: str | None, year: int | None, include_unlabeled: bool):
    """Queryset de valores (1 dict por anotação × autor). Sem paginação.

    Chaves cruas: ``external_id`` e ``relevance_label`` (o schema/``_row`` mapeiam
    para ``id`` e ``relevance``).
    """
    qs = PropositionAnnotation.objects.all()
    if not include_unlabeled:
        qs = qs.filter(is_favorable__isnull=False)
    if house:
        qs = qs.filter(proposition__house=house)
    if year:
        qs = qs.filter(proposition__year=year)

    return qs.values(
        # colunas do model saem com o próprio nome (alias com F() daria conflito)
        "is_favorable",  # bool cru
        "legacy_theme",  # "Tema (class humana)" da planilha, texto livre
        house=F("proposition__house"),
        external_id=F("proposition__external_id"),
        uri=F("proposition__tramitation_url"),
        type_code=F("proposition__type_code"),
        name=F("proposition__number_label"),
        year=F("proposition__year"),
        summary=F("proposition__ementa"),
        full_text=F("proposition__full_text"),
        author=Coalesce(
            F("proposition__authors__parliamentarian__full_name"),
            F("proposition__authors__institutional_author__name"),
        ),
        author_index=F("proposition__authors__order_index"),
        party=F("proposition__authors__party__acronym"),
        state=F("proposition__authors__state_at_authorship"),
        gender=_label_case(
            "proposition__authors__parliamentarian__gender", dict(Gender.choices)
        ),
        assessment=Case(
            When(is_favorable=True, then=Value("Favorável")),
            When(is_favorable=False, then=Value("Desfavorável")),
            default=Value(None),
            output_field=CharField(),
        ),
        relevance_label=_label_case("relevance", dict(HumanRelevance.choices)),
        # `theme` passa a ser a categoria (taxonomia fechada, rótulo em
        # português); o texto livre antigo continua disponível em `legacy_theme`.
        theme_label=_label_case("category", dict(PropositionCategory.choices)),
    ).order_by("id", "author_index")


def _row(d: dict) -> dict:
    """Linha do ``values()`` → dict ordenado com os nomes de saída."""
    return {
        "house": d["house"],
        "id": d["external_id"],
        "uri": d["uri"],
        "type_code": d["type_code"],
        "name": d["name"],
        "year": d["year"],
        "summary": d["summary"],
        "full_text": d["full_text"],
        "author": d["author"],
        "author_index": d["author_index"],
        "party": d["party"],
        "state": d["state"],
        "gender": d["gender"],
        "assessment": d["assessment"],
        "relevance": d["relevance_label"],
        "theme": d["theme_label"],
        "is_favorable": d["is_favorable"],
        "legacy_theme": d["legacy_theme"],
    }


# ── JSON paginado ─────────────────────────────────────────────────────────────

@router.get("", response=list[DatasetRowSchema])
@paginate(LimitOffsetPagination)
def dataset(
    request,
    house: str | None = None,
    year: int | None = None,
    include_unlabeled: bool = False,
):
    """Dataset rotulado (1 linha por anotação × autor), paginado (limit/offset)."""
    return _dataset_qs(house, year, include_unlabeled)


# ── download do dataset inteiro ───────────────────────────────────────────────

def _csv_stream(qs):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=FIELDS)
    writer.writeheader()
    yield buf.getvalue()
    for d in qs.iterator(chunk_size=1000):
        buf.seek(0)
        buf.truncate(0)
        writer.writerow(_row(d))
        yield buf.getvalue()


def _jsonl_stream(qs):
    for d in qs.iterator(chunk_size=1000):
        yield json.dumps(_row(d), ensure_ascii=False, default=str) + "\n"


def _parquet_bytes(qs) -> bytes:
    # Parquet é colunar → materializa tudo em memória (comprime bem no arquivo).
    import pyarrow as pa
    import pyarrow.parquet as pq

    # Estabiliza o pyarrow dentro do servidor: 1 thread + stream nativo (sem a
    # ponte Python BytesIO↔Arrow, que é onde ocorria o segfault).
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)
    rows = [_row(d) for d in qs.iterator(chunk_size=2000)]
    table = pa.table({f: [r[f] for r in rows] for f in FIELDS})
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink)
    return sink.getvalue().to_pybytes()


@router.get("/download")
def download(
    request,
    format: str = "csv",
    house: str | None = None,
    year: int | None = None,
    include_unlabeled: bool = False,
):
    """Baixa o dataset INTEIRO (sem paginação) em csv | parquet | jsonl."""
    qs = _dataset_qs(house, year, include_unlabeled)
    fmt = (format or "").lower()

    if fmt == "csv":
        resp = StreamingHttpResponse(_csv_stream(qs), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="dataset.csv"'
        return resp
    if fmt == "jsonl":
        resp = StreamingHttpResponse(_jsonl_stream(qs), content_type="application/x-ndjson")
        resp["Content-Disposition"] = 'attachment; filename="dataset.jsonl"'
        return resp
    if fmt == "parquet":
        resp = HttpResponse(_parquet_bytes(qs), content_type="application/vnd.apache.parquet")
        resp["Content-Disposition"] = 'attachment; filename="dataset.parquet"'
        return resp

    raise HttpError(400, "format inválido: use csv, parquet ou jsonl")
