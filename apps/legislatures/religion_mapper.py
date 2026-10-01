"""Map the public religious-identity spreadsheet to Câmara external IDs."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


class ReligionMappingError(ValueError):
    """The source cannot be safely mapped to one value per Câmara ID."""


@dataclass(frozen=True)
class ReligionMapping:
    values: dict[int, str]
    conflicting_ids: frozenset[int]


def map_religion_rows(rows: Iterable[Mapping[str, object]]) -> ReligionMapping:
    """Return ``{ID_Camara: Identidade Religiosa}`` from the source CSV.

    The source's own labels (including ``Sem Religião`` and ``Não
    identificada``) are editorial data and must not be collapsed into null.
    Conflicting repeated IDs are excluded instead of choosing an arbitrary
    value. The command reports them for manual review.
    """
    mapped: dict[int, str] = {}
    conflicting_ids: set[int] = set()
    for row in rows:
        raw_id = str(row.get("ID_Camara") or "").strip()
        religion = " ".join(str(row.get("Identidade Religiosa") or "").split())
        if not raw_id or not religion:
            continue
        try:
            external_id = int(raw_id)
        except ValueError as error:
            raise ReligionMappingError(f"ID_Camara inválido: {raw_id!r}") from error
        if external_id <= 0:
            raise ReligionMappingError(f"ID_Camara inválido: {raw_id!r}")

        if external_id in conflicting_ids:
            continue
        previous = mapped.setdefault(external_id, religion)
        if previous != religion:
            mapped.pop(external_id)
            conflicting_ids.add(external_id)
    return ReligionMapping(values=mapped, conflicting_ids=frozenset(conflicting_ids))
