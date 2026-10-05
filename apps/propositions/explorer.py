"""Server-owned filters, facets, pagination, export and dashboard for the explorer."""

import csv
import math
import re
import unicodedata
from collections import Counter
from io import StringIO
from typing import Literal

from django.core.cache import cache
from django.http import HttpResponse
from ninja import Field, Schema

SOURCE_CACHE_KEY = "activity:explorer:source:v1"
UNKNOWN_RELIGION = "__unknown__"
UFS = [
    "AC",
    "AL",
    "AM",
    "AP",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MG",
    "MS",
    "MT",
    "PA",
    "PB",
    "PE",
    "PI",
    "PR",
    "RJ",
    "RN",
    "RO",
    "RR",
    "RS",
    "SC",
    "SE",
    "SP",
    "TO",
]


class ExplorerQuery(Schema):
    search: str = ""
    house: str = ""
    year: int | None = None
    party: str = ""
    category: str = ""
    assessment: Literal["", "favorable", "unfavorable", "unrated"] = ""
    celerity: str = ""
    movements: Literal["", "with", "without"] = ""
    gender: str = ""
    state: str = ""
    religion: str = ""
    comments: Literal["", "yes", "no"] = ""
    evaluator: str = ""
    page: int = Field(1, ge=1)
    page_size: int = Field(10, ge=1, le=100)
    sort: Literal[
        "number", "author", "summary", "assessment", "evaluator", "progress", "category", "updated"
    ] = "updated"
    direction: Literal["ascending", "descending"] = "descending"
    party_sort: Literal["unfavorable", "favorable", "total"] = "unfavorable"
    author_sort: Literal["unfavorable", "favorable", "total"] = "unfavorable"
    author_minimum: int = Field(5, ge=1)


class FilterOptionSchema(Schema):
    value: str
    label: str


class DashboardRowSchema(Schema):
    key: str
    label: str
    favorable: int = 0
    unfavorable: int = 0
    photo: str | None = None
    meta: str | None = None
    favorable_width: float = 0
    unfavorable_width: float = 0
    favorable_percent: int | None = None
    color: str | None = None


class ExplorerSummarySchema(Schema):
    favorable: int
    unfavorable: int
    favorable_share: float
    active_filter_count: int


def _normalized(value):
    return "".join(
        char
        for char in unicodedata.normalize("NFD", str(value or "").strip())
        if not unicodedata.combining(char)
    ).lower()


def _gender(value):
    return {"f": "F", "feminino": "F", "m": "M", "masculino": "M"}.get(_normalized(value), "U")


def _state(value):
    state = str(value or "").strip().upper()
    return state if state in UFS else None


def _year(item):
    # The explorer historically uses the presentation year, not the ingestion year.
    return item["presented_at"].year


def _assessment(item):
    value = item["is_favorable"]
    return "unrated" if value is None else "favorable" if value else "unfavorable"


def _author_matches(author, query):
    religion = str(author.get("religion") or "").strip()
    return (
        (not query.gender or _gender(author["gender"]) == query.gender)
        and (not query.state or _state(author["state"]) == query.state)
        and (
            not query.religion
            or (query.religion == UNKNOWN_RELIGION and author["id"] is not None and not religion)
            or (
                query.religion != UNKNOWN_RELIGION
                and _normalized(religion) == _normalized(query.religion)
            )
        )
    )


def _matches(item, query):
    house = {"Deputado": "camara", "Senador": "senado"}.get(query.house, query.house)
    authors = item["authors"]
    search_text = " ".join(
        [
            item["number_label"],
            item["ementa"],
            item["assessment_organization"] or "",
            *(
                f"{author['name']} {author['party'] or ''} {author['state'] or ''}"
                for author in authors
            ),
        ]
    )
    author_filter = query.gender or query.state or query.religion
    movements = item["celerity"]["movements_last_90_days"]
    return (
        (not query.search.strip() or _normalized(query.search) in _normalized(search_text))
        and (not house or item["house"] == house)
        and (query.year is None or _year(item) == query.year)
        and (not query.party or any(author["party"] == query.party for author in authors))
        and (not query.category or _normalized(item["category"]) == _normalized(query.category))
        and (not query.assessment or _assessment(item) == query.assessment)
        and (not query.celerity or item["celerity"]["label"].strip() == query.celerity.strip())
        and (
            not query.movements or (movements > 0 if query.movements == "with" else movements == 0)
        )
        # A combined author filter must match one signer, not unrelated coauthors.
        and (not author_filter or any(_author_matches(author, query) for author in authors))
        and (
            not query.evaluator
            or _normalized(item["assessment_organization"]) == _normalized(query.evaluator)
        )
        and (
            not query.comments
            or bool((item["assessment_comments"] or "").strip()) == (query.comments == "yes")
        )
    )


def _all_activity():
    from .activity import ACTIVITY_CACHE_TIMEOUT, _queryset, _serialize

    items = cache.get(SOURCE_CACHE_KEY)
    if items is None:
        # No listing cap: filter and count the complete public collection before pagination.
        items = [
            _serialize(proposition, event_limit=0)
            for proposition in _queryset().order_by("-presented_at", "-pk")
        ]
        cache.set(SOURCE_CACHE_KEY, items, ACTIVITY_CACHE_TIMEOUT)
    return items


def _options(items):
    def options(values):
        return [
            {"value": str(value), "label": str(value)}
            for value in sorted(set(values), key=_normalized)
        ]

    authors = [author for item in items for author in item["authors"]]
    categories = {
        item["category"]: item["category_label"] or item["category"]
        for item in items
        if item["category"]
    }
    evaluators = {}
    religions = {}
    unknown_religion = False
    for item in items:
        evaluator = item["assessment_organization"]
        if evaluator:
            evaluators.setdefault(_normalized(evaluator), evaluator)
    for author in authors:
        religion = str(author.get("religion") or "").strip()
        if religion:
            religions.setdefault(_normalized(religion), religion)
        elif author["id"] is not None:
            unknown_religion = True
    religion_options = options(religions.values())
    if unknown_religion:
        religion_options.append({"value": UNKNOWN_RELIGION, "label": "Não informada"})
    return {
        "year": [
            {"value": str(year), "label": str(year)}
            for year in sorted({_year(item) for item in items}, reverse=True)
        ],
        "party": options(author["party"] for author in authors if author["party"]),
        "state": options(state for author in authors if (state := _state(author["state"]))),
        "category": [
            {"value": value, "label": label}
            for value, label in sorted(categories.items(), key=lambda pair: _normalized(pair[1]))
        ],
        "evaluator": options(evaluators.values()),
        "celerity": options(item["celerity"]["label"] for item in items),
        "religion": religion_options,
    }


def _person_key(author):
    return (
        f"person:num:{author['id']}"
        if author["id"] is not None
        else f"person:name:{_normalized(author['name'])}"
    )


def _increment(groups, key, label, item, **details):
    row = groups.setdefault(
        key, {"key": key, "label": label, "favorable": 0, "unfavorable": 0, **details}
    )
    if item["is_favorable"] is True:
        row["favorable"] += 1
    elif item["is_favorable"] is False:
        row["unfavorable"] += 1


def _dashboard_sort(rows, mode):
    def order(row):
        total = row["favorable"] + row["unfavorable"]
        favorable = row["favorable"] / total if total else 0
        unfavorable = row["unfavorable"] / total if total else 0
        primary = total if mode == "total" else favorable if mode == "favorable" else unfavorable
        secondary = unfavorable if mode == "total" else total
        return (-primary, -secondary, _natural_key(row["label"]))

    return sorted(rows, key=order)


def _map_color(rate):
    if rate is None:
        return "#998D96"
    stops = [
        (0.60, "#FF5865"),
        (0.65, "#FF9098"),
        (0.70, "#FFC7CC"),
        (0.75, "#FFFFFF"),
        (0.80, "#EAF7BD"),
        (0.85, "#D6EE7B"),
        (0.90, "#C1E639"),
    ]
    if rate <= stops[0][0]:
        return stops[0][1]
    if rate >= stops[-1][0]:
        return stops[-1][1]
    for (lower, start), (upper, end) in zip(stops, stops[1:], strict=False):
        if rate <= upper:
            amount = (rate - lower) / (upper - lower)
            channels = [
                math.floor(
                    int(start[index : index + 2], 16)
                    + (int(end[index : index + 2], 16) - int(start[index : index + 2], 16)) * amount
                    + 0.5
                )
                for index in (1, 3, 5)
            ]
            return "#" + "".join(f"{channel:02X}" for channel in channels)
    raise AssertionError("Unreachable map rate")


def _dashboard(items, query):
    groups = {
        key: {} for key in ("gender", "house", "party", "author", "state", "category", "status")
    }
    author_counts = Counter()
    for item in items:
        if item["house"] in ("camara", "senado"):
            _increment(
                groups["house"],
                item["house"],
                {"camara": "Câmara", "senado": "Senado"}[item["house"]],
                item,
            )
        if item["category"]:
            _increment(
                groups["category"],
                item["category"],
                item["category_label"] or item["category"],
                item,
            )
        status = (item["current_status"] or "").strip()
        _increment(groups["status"], status or "unavailable", status or "Não informado", item)
        seen = set()
        for author in item["authors"]:
            key = _person_key(author)
            if key in seen or not _author_matches(author, query):
                continue
            seen.add(key)
            author_counts[key] += 1
            _increment(
                groups["author"],
                key,
                author["name"],
                item,
                photo=author["photo_url"],
                meta="/".join(value for value in (author["party"], author["state"]) if value),
            )
            party = (author["party"] or "").strip() or "Indefinido"
            _increment(groups["party"], party, party, item)
            gender = _gender(author["gender"])
            if gender in ("F", "M"):
                _increment(
                    groups["gender"], gender, {"F": "Feminino", "M": "Masculino"}[gender], item
                )
            state = _state(author["state"])
            if state:
                _increment(groups["state"], state, state, item)
    result = {key: list(rows.values()) for key, rows in groups.items()}
    result["gender"] = [groups["gender"][key] for key in ("F", "M") if key in groups["gender"]]
    result["house"] = [
        groups["house"][key] for key in ("camara", "senado") if key in groups["house"]
    ]
    result["party"] = _dashboard_sort(result["party"], query.party_sort)
    result["author"] = _dashboard_sort(
        [row for row in result["author"] if author_counts[row["key"]] >= query.author_minimum],
        query.author_sort,
    )
    # Return all states so the browser never derives rates, colors or missing data.
    result["state"] = [
        groups["state"].get(uf, {"key": uf, "label": uf, "favorable": 0, "unfavorable": 0})
        for uf in UFS
    ]
    for rows in result.values():
        peak = max([1, *(max(row["favorable"], row["unfavorable"]) for row in rows)])
        for row in rows:
            row["favorable_width"] = row["favorable"] / peak * 100
            row["unfavorable_width"] = row["unfavorable"] / peak * 100
    for row in result["state"]:
        total = row["favorable"] + row["unfavorable"]
        rate = row["favorable"] / total if total else None
        row["favorable_percent"] = math.floor(rate * 100 + 0.5) if rate is not None else None
        row["color"] = _map_color(rate)
    return result


def _natural_key(value):
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in re.split(r"(\d+)", _normalized(value))
    )


def _sort_items(items, query):
    fields = {
        "number": "number_label",
        "summary": "ementa",
        "evaluator": "assessment_organization",
        "category": "category",
    }

    def key(item):
        if query.sort == "updated":
            primary = item["presented_at"]
        elif query.sort == "assessment":
            primary = 0 if item["is_favorable"] is None else 1 if item["is_favorable"] else -1
        elif query.sort == "progress":
            primary = item["celerity"]["movements_last_90_days"]
        elif query.sort == "author":
            primary = _natural_key(item["authors"][0]["name"] if item["authors"] else "")
        else:
            primary = _natural_key(item[fields[query.sort]])
        return (primary, item["id"])

    return sorted(items, key=key, reverse=query.direction == "descending")


def explore_activity(query):
    source = _all_activity()
    items = _sort_items([item for item in source if _matches(item, query)], query)
    total = len(items)
    page_count = max(1, math.ceil(total / query.page_size))
    page = min(query.page, page_count)
    start = (page - 1) * query.page_size
    favorable = sum(item["is_favorable"] is True for item in items)
    unfavorable = sum(item["is_favorable"] is False for item in items)
    filter_names = (
        "search",
        "house",
        "year",
        "party",
        "category",
        "assessment",
        "celerity",
        "movements",
        "gender",
        "state",
        "religion",
        "comments",
        "evaluator",
    )
    return {
        "items": items[start : start + query.page_size],
        "total": total,
        "page": page,
        "page_count": page_count,
        "options": _options(source),
        "summary": {
            "favorable": favorable,
            "unfavorable": unfavorable,
            "favorable_share": favorable / (favorable + unfavorable) * 100
            if favorable + unfavorable
            else 0,
            "active_filter_count": sum(bool(getattr(query, name)) for name in filter_names),
        },
        "dashboard": _dashboard(items, query),
    }


def export_activity(query):
    items = _sort_items([item for item in _all_activity() if _matches(item, query)], query)
    output = StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_ALL)
    writer.writerow(
        [
            "Proposição",
            "Casa",
            "Ano",
            "Autoria",
            "Partido/UF",
            "Ementa",
            "Avaliação",
            "Quem avaliou",
            "Ressalvas",
            "Categoria",
            "Situação",
        ]
    )
    for item in items:
        writer.writerow(
            [
                item["number_label"],
                item["house"],
                _year(item),
                "; ".join(author["name"] for author in item["authors"]),
                "; ".join(
                    "/".join(value or "" for value in (author["party"], author["state"]))
                    for author in item["authors"]
                ),
                item["ementa"],
                {
                    "favorable": "Favorável",
                    "unfavorable": "Desfavorável",
                    "unrated": "Sem avaliação",
                }[_assessment(item)],
                item["assessment_organization"] or "",
                item["assessment_comments"] or "",
                item["category_label"] or item["category"] or "",
                item["current_status"] or "",
            ]
        )
    response = HttpResponse(output.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="atividade-legislativa.csv"'
    return response
