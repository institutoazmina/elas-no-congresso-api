"""Conservative matching of official Câmara → Senado transfers."""

from apps.propositions.models import Proposition


def senate_origin(process: dict) -> dict | None:
    """Only trust the Senate's explicit identity for a Câmara-origin matter."""
    if process.get("siglaCasaIniciadora") != "CD" or process.get("casaIdentificadora") != "SF":
        return None
    candidates = [
        number
        for number in process.get("outrosNumeros", []) or []
        if number.get("casaIdentificadora") == "CD" and number.get("siglaEnteIdentificador") == "CD"
    ]
    if len(candidates) != 1:
        return None
    number = candidates[0]
    try:
        identity = {
            "type_code": str(number["sigla"]).upper(),
            "number": int(number["numero"]),
            "year": int(number["ano"]),
        }
    except (KeyError, TypeError, ValueError):
        return None
    if identity["type_code"] != "PL" or identity["number"] <= 0:
        return None
    try:
        process_identity = (
            str(process.get("sigla", "")).upper(),
            int(process.get("numero") or 0),
            int(process.get("ano") or 0),
        )
    except (TypeError, ValueError):
        return None
    if process_identity != (identity["type_code"], identity["number"], identity["year"]):
        return None
    return identity


def find_camara_origin(identity: dict | None) -> Proposition | None:
    """Require an unambiguous official Câmara record with remittance history."""
    if not isinstance(identity, dict):
        return None
    if (
        identity.get("type_code") != "PL"
        or not isinstance(identity.get("number"), int)
        or not isinstance(identity.get("year"), int)
    ):
        return None
    candidates = list(
        Proposition.objects.filter(
            house="camara", number=identity["number"], year=identity["year"]
        ).filter(type_code__iexact=identity["type_code"])[:2]
    )
    if len(candidates) != 1:
        return None
    original = candidates[0]
    if (
        original.canonical_proposition_id
        or not original.events.filter(dispatch__icontains="Remessa ao Senado Federal").exists()
    ):
        return None
    return original


def link_senate_transfer(receiving: Proposition) -> Proposition | None:
    """Link an imported Senate source when its unique origin and remittance exist."""
    identity = (receiving.raw_payload or {}).get("_house_transfer")
    if (
        receiving.house != "senado"
        or receiving.originating_house != "camara"
        or not isinstance(identity, dict)
    ):
        return None
    if (receiving.type_code.upper(), receiving.number, receiving.year) != (
        "PL",
        identity.get("number"),
        identity.get("year"),
    ):
        return None
    original = find_camara_origin(identity)
    if original is None:
        return None
    if receiving.canonical_proposition_id not in (None, original.pk):
        return None
    if receiving.canonical_proposition_id is None:
        Proposition.objects.filter(pk=receiving.pk, canonical_proposition__isnull=True).update(
            canonical_proposition=original
        )
        receiving.canonical_proposition_id = original.pk
    return original


def link_pending_senate_transfers(original: Proposition) -> list[Proposition]:
    """Handle a Câmara source that arrives after the Senate import."""
    if original.house != "camara" or original.type_code.upper() != "PL":
        return []
    linked = []
    for receiving in Proposition.objects.filter(
        house="senado",
        originating_house="camara",
        canonical_proposition__isnull=True,
        number=original.number,
        year=original.year,
    ):
        if link_senate_transfer(receiving) == original:
            linked.append(receiving)
    return linked
