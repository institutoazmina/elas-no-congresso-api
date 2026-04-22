"""Reference matcher — Python-pure oracle for correctness testing (ported from POC)."""
from __future__ import annotations

from datetime import date
from typing import Any


def matches(ast: dict, proposition: dict) -> bool:
    op = ast.get("op")

    if op == "AND":
        return all(matches(child, proposition) for child in ast["children"])
    if op == "OR":
        return any(matches(child, proposition) for child in ast["children"])
    if op == "NOT":
        return not matches(ast["child"], proposition)

    field = ast["field"]
    leaf_op = ast["op"]
    filter_val = ast["value"]
    prop_val = proposition.get(field)

    if prop_val is None and leaf_op not in ("ne",):
        return False

    if leaf_op == "eq":
        if isinstance(prop_val, list):
            return any(_coerce_eq(pv, filter_val) for pv in prop_val)
        if isinstance(filter_val, list):
            return any(_coerce_eq(prop_val, fv) for fv in filter_val)
        return _coerce_eq(prop_val, filter_val)

    if leaf_op == "ne":
        if prop_val is None:
            return True
        return not _coerce_eq(prop_val, filter_val)

    if leaf_op == "in":
        if isinstance(prop_val, list):
            return any(_coerce_eq(pv, fv) for pv in prop_val for fv in filter_val)
        return any(_coerce_eq(prop_val, fv) for fv in filter_val)

    if leaf_op == "contains":
        if isinstance(prop_val, list):
            return any(_coerce_eq(pv, filter_val) for pv in prop_val)
        return str(filter_val).lower() in str(prop_val).lower()

    p = _coerce_comparable(prop_val)
    f = _coerce_comparable(filter_val)

    if leaf_op == "gte":
        return p >= f
    if leaf_op == "lte":
        return p <= f
    if leaf_op == "gt":
        return p > f
    if leaf_op == "lt":
        return p < f
    if leaf_op == "between":
        lo = _coerce_comparable(filter_val[0])
        hi = _coerce_comparable(filter_val[1])
        return lo <= p <= hi

    raise ValueError(f"Unknown op: {leaf_op!r}")


def _coerce_eq(a: Any, b: Any) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a.lower() == b.lower()
    if isinstance(a, list) and isinstance(b, str):
        return any(_coerce_eq(item, b) for item in a)
    if isinstance(b, list) and isinstance(a, str):
        return any(_coerce_eq(a, item) for item in b)
    if isinstance(a, list) and isinstance(b, list):
        return any(_coerce_eq(ai, bi) for ai in a for bi in b)
    if a is not None and b is not None:
        try:
            if isinstance(a, (int, float)) or isinstance(b, (int, float)):
                return abs(float(a) - float(b)) < 1e-9
        except (ValueError, TypeError):
            pass
    return a == b


def _coerce_comparable(v: Any):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return date.fromisoformat(v)
        except ValueError:
            pass
        try:
            return float(v)
        except ValueError:
            pass
    return v
