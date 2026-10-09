"""AST → tsquery compiler (ported verbatim from poc4_real_db_tsquery)."""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def _remove_accents(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


_TSQUERY_RESERVED = re.compile(r"[&|!:<>()\s\'\-]")


def _sanitize_token(s: str) -> str:
    s = str(s).lower()
    s = _remove_accents(s)
    s = _TSQUERY_RESERVED.sub("_", s)
    s = re.sub(r"_+", "_", s)
    s = s.strip("_")
    return s or "unknown"


def _make_token(field: str, value: Any) -> str:
    return f"{_sanitize_token(field)}_{_sanitize_token(str(value))}"


NUMERIC_TOKEN_FIELDS = {
    "quiteriometro": ("quiter", -10, 10),
    "ano": ("ano", 2000, 2030),
}

SCALAR_FIELDS = ("tipo", "casa", "situacao", "ano", "proposicao")
# `relator` é lista no documento (uma proposição pode ter mais de um).
ARRAY_FIELDS = (
    "partido", "autor", "genero", "raca", "religiao",
    "estado", "relator", "tema", "categoria", "comissao", "frente", "bancada", "norma",
)
# Campos que `build_document` preenche; qualquer outro nunca casaria.
KNOWN_FIELDS = frozenset(SCALAR_FIELDS + ARRAY_FIELDS) | frozenset(NUMERIC_TOKEN_FIELDS)
LEAF_OPS = frozenset({"eq", "ne", "in", "contains", "gt", "gte", "lt", "lte", "between"})


def validate_ast(ast: Any) -> None:
    """Recusa critérios que compilariam para uma consulta sem sentido.

    Chamado na entrada (API e admin). O compilador continua aceitando a forma
    antiga para não quebrar inscrições já gravadas.
    """
    if not isinstance(ast, dict):
        raise ValueError("cada nó do filtro deve ser um objeto")
    op = ast.get("op")
    if not isinstance(op, str):
        raise ValueError("nó sem operador")
    upper = op.upper()
    if upper in ("AND", "OR"):
        children = ast.get("children")
        if not isinstance(children, list) or not children:
            raise ValueError(f"{upper} precisa de ao menos um filtro")
        for child in children:
            validate_ast(child)
        return
    if upper == "NOT":
        validate_ast(ast.get("child"))
        return
    if op not in LEAF_OPS:
        raise ValueError(f"operador desconhecido: {op!r}")
    field = ast.get("field")
    if field not in KNOWN_FIELDS:
        raise ValueError(f"campo desconhecido: {field!r}")
    value = ast.get("value")
    if op == "in" and (not isinstance(value, list) or not value):
        raise ValueError("'in' exige uma lista não vazia")
    if op == "between" and (not isinstance(value, list) or len(value) != 2):
        raise ValueError("'between' exige [mínimo, máximo]")
    if op in ("gt", "gte", "lt", "lte", "between") and field not in NUMERIC_TOKEN_FIELDS:
        raise ValueError(f"{op!r} só vale para campos numéricos")
    if op not in ("in", "between") and (value is None or isinstance(value, (list, dict))):
        raise ValueError(f"{op!r} exige um valor simples")


def _leaf_to_tsquery(leaf: dict) -> tuple[str, bool]:
    field = leaf.get("field", "")
    op = leaf.get("op", "eq")
    value = leaf.get("value", "")
    needs_reval = False
    prefix = _sanitize_token(field)  # noqa: F841

    if op == "eq":
        if field in NUMERIC_TOKEN_FIELDS:
            tok_prefix, lo, hi = NUMERIC_TOKEN_FIELDS[field]  # noqa: F841
            v_int = int(float(value))
            tok = f"{tok_prefix}_eq_{v_int}"
            needs_reval = True
            return tok, needs_reval
        return _make_token(field, value), False

    if op == "ne":
        if field in NUMERIC_TOKEN_FIELDS:
            tok_prefix, lo, hi = NUMERIC_TOKEN_FIELDS[field]  # noqa: F841
            v_int = int(float(value))
            tok = f"!{tok_prefix}_eq_{v_int}"
        else:
            tok = f"!{_make_token(field, value)}"
        return tok, True

    if op == "in":
        tokens = []
        for v in value:
            if field in NUMERIC_TOKEN_FIELDS:
                tok_prefix, _, __ = NUMERIC_TOKEN_FIELDS[field]
                v_int = int(float(v))
                tokens.append(f"{tok_prefix}_eq_{v_int}")
            else:
                tokens.append(_make_token(field, v))
        return "(" + " | ".join(tokens) + ")", False

    if op == "contains":
        tok = _make_token(field, value)
        return tok, False

    if op in ("gte", "gt"):
        if field in NUMERIC_TOKEN_FIELDS:
            tok_prefix, lo, hi = NUMERIC_TOKEN_FIELDS[field]  # noqa: F841
            v_int = int(float(value))
            needs_reval = True
            tok = f"{tok_prefix}_ge_{v_int}"
            return tok, needs_reval
        return _make_token(field, value), True

    if op in ("lte", "lt"):
        if field in NUMERIC_TOKEN_FIELDS:
            tok_prefix, lo, hi = NUMERIC_TOKEN_FIELDS[field]  # noqa: F841
            v_int = int(float(value))
            needs_reval = True
            tok = f"{tok_prefix}_le_{v_int}"
            return tok, needs_reval
        return _make_token(field, value), True

    if op == "between":
        lo_val, hi_val = value[0], value[1]
        if field in NUMERIC_TOKEN_FIELDS:
            tok_prefix, lo, hi = NUMERIC_TOKEN_FIELDS[field]  # noqa: F841
            lo_int = int(float(lo_val))
            hi_int = int(float(hi_val))
            needs_reval = True
            tok_lo = f"{tok_prefix}_ge_{lo_int}"
            tok_hi = f"{tok_prefix}_le_{hi_int}"
            return f"({tok_lo} & {tok_hi})", needs_reval
        return _make_token(field, lo_val), True

    raise ValueError(f"Unknown leaf op: {op!r}")


def ast_to_tsquery(ast: dict) -> tuple[str, bool]:
    op = ast.get("op", "").upper()

    if op not in ("AND", "OR", "NOT"):
        return _leaf_to_tsquery(ast)

    if op == "AND":
        parts = []
        needs_reval = False
        for child in ast.get("children", []):
            s, r = ast_to_tsquery(child)
            parts.append(f"({s})")
            needs_reval = needs_reval or r
        return " & ".join(parts), needs_reval

    if op == "OR":
        parts = []
        needs_reval = False
        for child in ast.get("children", []):
            s, r = ast_to_tsquery(child)
            parts.append(f"({s})")
            needs_reval = needs_reval or r
        return " | ".join(parts), needs_reval

    if op == "NOT":
        s, r = ast_to_tsquery(ast.get("child", {}))
        return f"!({s})", True

    raise ValueError(f"Unknown op: {op!r}")


def document_to_tsvector_tokens(prop: dict) -> list[str]:
    tokens = []

    for field in SCALAR_FIELDS:
        v = prop.get(field)
        if v is not None:
            tokens.append(_make_token(field, v))

    for field in ARRAY_FIELDS:
        vals = prop.get(field, [])
        for v in vals:
            tokens.append(_make_token(field, v))

    for field, (tok_prefix, lo, hi) in NUMERIC_TOKEN_FIELDS.items():
        v = prop.get(field)
        if v is None:
            continue
        v_int = int(float(v))
        for n in range(lo, v_int + 1):
            tokens.append(f"{tok_prefix}_ge_{n}")
        for n in range(v_int, hi + 1):
            tokens.append(f"{tok_prefix}_le_{n}")
        tokens.append(f"{tok_prefix}_eq_{v_int}")

    return tokens


def document_to_tsvector_string(prop: dict) -> str:
    tokens = document_to_tsvector_tokens(prop)
    seen: set[str] = set()
    unique = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return " ".join(unique)
