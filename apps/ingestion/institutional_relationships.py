"""Persist official parliamentarian institutional relationships.

Provider identity keys are deliberately namespaced by entity type.  For example,
``orgao:88`` and ``comissao:88`` cannot collide even if the providers reuse a
numeric identifier across endpoints.  Membership keys append the selected
term's provider parliamentarian id; no name-based identity resolution occurs.
"""

import re
import unicodedata
from collections.abc import Mapping
from datetime import date, datetime

from django.db import transaction
from django.utils import timezone

from apps.committees.models import (
    Caucus,
    CaucusMembership,
    Committee,
    CommitteeMembership,
    CommitteePresidency,
)
from apps.core.enums import CaucusKind
from apps.legislatures.models import ParliamentarianPost, ParliamentarianTerm


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first(record: Mapping, *keys: str) -> str | None:
    for key in keys:
        value = _text(record.get(key))
        if value is not None:
            return value
    return None


def parse_provider_date(value: object) -> date | None:
    """Parse only an explicitly supplied provider date; never infer one."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    value = _text(value)
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _date_from(record: Mapping, *keys: str) -> date | None:
    for key in keys:
        if key in record:
            return parse_provider_date(record[key])
    return None


def _stable_component(*values: object) -> str:
    value = "|".join(_text(item) or "" for item in values)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.casefold()).strip("-")
    return value or "unknown"


def _provider_key(
    prefix: str,
    record: Mapping,
    id_keys: tuple[str, ...],
    composite_keys: tuple[str, ...],
) -> str | None:
    provider_id = _first(record, *id_keys)
    if provider_id:
        return f"{prefix}:{provider_id}"
    composite = _stable_component(*(record.get(key) for key in composite_keys))
    if composite == "unknown":
        return None
    return f"{prefix}:composite:{composite}"


def _url(record: Mapping, fallback: str) -> str:
    return _first(record, "uri", "uriOrgao", "UriComissao", "UrlComissao", "url") or fallback


def _role(record: Mapping) -> str | None:
    return _first(
        record,
        "titulo",
        "Titulo",
        "cargo",
        "Cargo",
        "CargoComissao",
        "funcao",
        "Funcao",
        "tipoParticipacao",
        "TipoParticipacao",
        "descricaoTipo",
        "DescricaoTipo",
        "descricaoTipoLideranca",
        "DescricaoTipoLideranca",
    )


def _caucus_role(record: Mapping) -> str | None:
    return _first(
        record,
        "role",
        "Role",
        "cargo",
        "Cargo",
        "funcao",
        "Funcao",
        "tipoParticipacao",
        "TipoParticipacao",
        "descricaoTipoLideranca",
        "DescricaoTipoLideranca",
    )


def is_committee_president(record: Mapping) -> bool:
    """Return true only for an explicit committee-president role."""
    role_keys = (
        "cargo",
        "Cargo",
        "CargoComissao",
        "cargoComissao",
        "titulo",
        "Titulo",
        "funcao",
        "Funcao",
        "papel",
        "Papel",
        "DescricaoCargo",
        "descricaoCargo",
    )
    explicit_president = False
    for key in role_keys:
        role = _text(record.get(key))
        if not role:
            continue
        normalized = _stable_component(role)
        if "vice-presidente" in normalized or normalized.startswith("vice-"):
            return False
        if normalized == "presidente" or normalized.startswith("presidente-"):
            explicit_president = True
    return explicit_president


def _touch(
    model,
    identity: Mapping[str, object],
    defaults: Mapping[str, object],
    *,
    create_defaults: Mapping[str, object] | None = None,
):
    now = timezone.now()
    obj = model.objects.filter(**identity).first()
    if obj is None:
        return model.objects.create(
            **identity,
            **{**(create_defaults or {}), **defaults},
            first_seen_at=now,
            last_seen_at=now,
        )

    changed_fields = []
    for field, value in defaults.items():
        if value is None or value == "":
            continue
        if getattr(obj, field) != value:
            setattr(obj, field, value)
            changed_fields.append(field)
    if obj.first_seen_at is None:
        obj.first_seen_at = now
        changed_fields.append("first_seen_at")
    obj.last_seen_at = now
    changed_fields.append("last_seen_at")
    if changed_fields:
        obj.save(update_fields=list(dict.fromkeys(changed_fields)))
    return obj


def _committee(
    *,
    source: str,
    source_key: str,
    house: str,
    record: Mapping,
    fallback_url: str,
) -> Committee | None:
    name = _first(record, "nomeOrgao", "NomeOrgao", "NomeComissao", "nome", "nomeComissao")
    raw_acronym = _first(
        record,
        "siglaOrgao",
        "SiglaOrgao",
        "SiglaComissao",
        "sigla",
        "acronym",
    )
    raw_kind = _first(record, "tipoOrgao", "TipoOrgao", "TipoComissao", "tipo")
    identity = {"source": source, "source_key": source_key}
    if not name and not Committee.objects.filter(**identity).exists():
        return None
    defaults = {
        "house": house,
        "source_url": _url(record, fallback_url),
        "is_active": True,
    }
    if name:
        defaults["name"] = name
    if raw_acronym:
        defaults["acronym"] = raw_acronym
    if raw_kind:
        defaults["kind"] = raw_kind
    return _touch(
        Committee,
        identity,
        defaults,
        create_defaults={
            "acronym": raw_acronym or _stable_component(name).upper(),
            "name": name or raw_acronym or source_key,
            "kind": raw_kind or "orgao",
        },
    )


def _committee_membership(
    *,
    source: str,
    source_key: str,
    committee: Committee,
    term: ParliamentarianTerm,
    record: Mapping,
    fallback_url: str,
) -> CommitteeMembership:
    role = _role(record) or "membro"
    defaults = {
        "committee": committee,
        "parliamentarian": term.parliamentarian,
        "legislature": term.legislature_number,
        "role": _role(record),
        "start_date": _date_from(
            record, "dataInicio", "DataInicio", "dataEntrada", "DataEntrada"
        ),
        "end_date": _date_from(record, "dataFim", "DataFim", "dataSaida", "DataSaida"),
        "is_observed_current": True,
        "source_url": _url(record, fallback_url),
    }
    return _touch(
        CommitteeMembership,
        {"source": source, "source_key": source_key},
        defaults,
        create_defaults={"role": role},
    )


def _committee_presidency(
    *,
    source: str,
    membership_source_key: str,
    committee: Committee,
    term: ParliamentarianTerm,
    record: Mapping,
    fallback_url: str,
) -> CommitteePresidency:
    defaults = {
        "committee": committee,
        "parliamentarian": term.parliamentarian,
        "legislature": term.legislature_number,
        "start_date": _date_from(
            record, "dataInicio", "DataInicio", "dataEntrada", "DataEntrada"
        ),
        "end_date": _date_from(record, "dataFim", "DataFim", "dataSaida", "DataSaida"),
        "is_observed_current": True,
        "source_url": _url(record, fallback_url),
    }
    return _touch(
        CommitteePresidency,
        {
            "source": source,
            "source_key": f"{membership_source_key}:presidency",
        },
        defaults,
    )


def _caucus(
    *,
    source: str,
    source_key: str,
    house: str,
    kind: str,
    name: str,
    term: ParliamentarianTerm | None,
    record: Mapping,
    fallback_url: str,
) -> Caucus:
    defaults = {
        "house": house,
        "kind": kind,
        "name": name,
        "legislature": term.legislature_number if term is not None else None,
        "description": _first(record, "status", "Status", "situacao", "Situacao"),
        "source_url": _url(record, fallback_url),
        "start_date": _date_from(
            record, "dataInicio", "DataInicio", "dataFiliacao", "DataFiliacao"
        ),
        "end_date": _date_from(record, "dataFim", "DataFim", "dataDesfiliacao", "DataDesfiliacao"),
        "is_active": True,
    }
    return _touch(Caucus, {"source": source, "source_key": source_key}, defaults)


def _caucus_membership(
    *,
    source: str,
    source_key: str,
    caucus: Caucus,
    term: ParliamentarianTerm,
    record: Mapping,
    fallback_url: str,
) -> CaucusMembership:
    defaults = {
        "caucus": caucus,
        "parliamentarian": term.parliamentarian,
        "role": _caucus_role(record),
        "start_date": _date_from(
            record, "dataInicio", "DataInicio", "dataFiliacao", "DataFiliacao"
        ),
        "end_date": _date_from(record, "dataFim", "DataFim", "dataDesfiliacao", "DataDesfiliacao"),
        "is_observed_current": True,
        "source_url": _url(record, fallback_url),
    }
    return _touch(
        CaucusMembership,
        {"source": source, "source_key": source_key},
        defaults,
    )


def _post(
    *,
    source: str,
    source_key: str,
    house: str,
    term: ParliamentarianTerm,
    title: str,
    record: Mapping,
    fallback_url: str,
) -> ParliamentarianPost:
    defaults = {
        "parliamentarian": term.parliamentarian,
        "house": house,
        "legislature": term.legislature_number,
        "title": title,
        "organization_name": _first(
            record,
            "nomeOrgao",
            "NomeOrgao",
            "NomeInstituicao",
            "NomeBloco",
            "NomeBancada",
            "orgao",
            "Orgao",
        ),
        "start_date": _date_from(
            record, "dataInicio", "DataInicio", "dataEntrada", "DataEntrada"
        ),
        "end_date": _date_from(record, "dataFim", "DataFim", "dataSaida", "DataSaida"),
        "is_observed_current": True,
        "source_url": _url(record, fallback_url),
    }
    return _touch(ParliamentarianPost, {"source": source, "source_key": source_key}, defaults)


def _persist_camara(term: ParliamentarianTerm, client) -> dict[str, int]:
    external_id = term.external_id
    fronts = client.fetch_deputy_fronts(external_id)
    organs = client.fetch_deputy_organs(external_id)
    source = "camara"
    base_url = getattr(client, "base_url", "https://dadosabertos.camara.leg.br/api/v2")
    counts = {"caucuses": 0, "committees": 0, "memberships": 0}

    for front in fronts:
        key = _provider_key(
            "front",
            front,
            ("id", "idFrente", "CodigoFrente"),
            ("titulo", "nome", "dataInicio", "dataFim"),
        )
        name = _first(front, "titulo", "nome", "nomeFrente")
        if not key or not name:
            continue
        entity_url = _url(front, f"{base_url}/frentes/{key.rsplit(':', 1)[-1]}")
        caucus = _caucus(
            source=source,
            source_key=key,
            house="camara",
            kind=CaucusKind.FRENTE,
            name=name,
            term=term,
            record=front,
            fallback_url=entity_url,
        )
        _caucus_membership(
            source=source,
            source_key=f"{key}:member:{external_id}",
            caucus=caucus,
            term=term,
            record=front,
            fallback_url=entity_url,
        )
        counts["caucuses"] += 1
        counts["memberships"] += 1

    for organ in organs:
        key = _provider_key(
            "orgao",
            organ,
            ("idOrgao", "id", "CodigoOrgao", "codigoOrgao"),
            ("siglaOrgao", "nomeOrgao", "tipoOrgao"),
        )
        if not key:
            continue
        entity_url = _url(organ, f"{base_url}/orgaos/{key.rsplit(':', 1)[-1]}")
        committee = _committee(
            source=source,
            source_key=key,
            house="camara",
            record=organ,
            fallback_url=entity_url,
        )
        if committee is None:
            continue
        membership_source_key = f"{key}:member:{external_id}"
        _committee_membership(
            source=source,
            source_key=membership_source_key,
            committee=committee,
            term=term,
            record=organ,
            fallback_url=entity_url,
        )
        if is_committee_president(organ):
            _committee_presidency(
                source=source,
                membership_source_key=membership_source_key,
                committee=committee,
                term=term,
                record=organ,
                fallback_url=entity_url,
            )
        counts["committees"] += 1
        counts["memberships"] += 1
    return counts


def _formal_group(record: Mapping) -> tuple[str, str, str] | None:
    pairs = (
        (CaucusKind.BANCADA, ("CodigoBancada", "IdBancada", "idBancada"), ("NomeBancada", "nomeBancada")),
        (CaucusKind.BLOCO, ("CodigoBloco", "IdBloco", "idBloco"), ("NomeBloco", "nomeBloco")),
    )
    for kind, id_keys, name_keys in pairs:
        group_id = _first(record, *id_keys)
        group_name = _first(record, *name_keys)
        if group_id and group_name:
            return kind, group_id, group_name
    return None


def _persist_senado(term: ParliamentarianTerm, client) -> dict[str, int]:
    external_id = term.external_id
    committees = client.fetch_senator_committees(external_id)
    affiliations = client.fetch_senator_party_affiliations(external_id)
    leaderships = client.fetch_senator_leaderships(external_id)
    posts = client.fetch_senator_posts(external_id)
    source = "senado"
    base_url = getattr(client, "base_url", "https://legis.senado.leg.br/dadosabertos")
    committee_url = f"{base_url}/senador/{external_id}/comissoes"
    counts = {"caucuses": 0, "committees": 0, "memberships": 0, "posts": 0}

    for committee_record in committees:
        key = _provider_key(
            "comissao",
            committee_record,
            ("CodigoComissao", "IdComissao", "idComissao", "CodigoOrgao"),
            ("SiglaComissao", "NomeComissao"),
        )
        if not key:
            continue
        entity_url = _url(committee_record, committee_url)
        committee = _committee(
            source=source,
            source_key=key,
            house="senado",
            record=committee_record,
            fallback_url=entity_url,
        )
        if committee is None:
            continue
        membership_source_key = f"{key}:member:{external_id}"
        _committee_membership(
            source=source,
            source_key=membership_source_key,
            committee=committee,
            term=term,
            record=committee_record,
            fallback_url=entity_url,
        )
        if is_committee_president(committee_record):
            _committee_presidency(
                source=source,
                membership_source_key=membership_source_key,
                committee=committee,
                term=term,
                record=committee_record,
                fallback_url=entity_url,
            )
        counts["committees"] += 1
        counts["memberships"] += 1

    group_records = [
        (record, "filiacoes") for record in affiliations
    ] + [(record, "liderancas") for record in leaderships]
    for group_record, group_endpoint in group_records:
        formal_group = _formal_group(group_record)
        if not formal_group:
            continue
        kind, group_id, group_name = formal_group
        key = f"group:{kind}:{group_id}"
        entity_url = _url(group_record, f"{base_url}/senador/{external_id}/{group_endpoint}")
        caucus = _caucus(
            source=source,
            source_key=key,
            house="senado",
            kind=kind,
            name=group_name,
            term=term,
            record=group_record,
            fallback_url=entity_url,
        )
        _caucus_membership(
            source=source,
            source_key=f"{key}:member:{external_id}",
            caucus=caucus,
            term=term,
            record=group_record,
            fallback_url=entity_url,
        )
        counts["caucuses"] += 1
        counts["memberships"] += 1

    leadership_url = f"{base_url}/senador/{external_id}/liderancas"
    for leadership in leaderships:
        key = _provider_key(
            "lideranca",
            leadership,
            ("CodigoLideranca", "IdLideranca", "idLideranca"),
            (
                "DescricaoTipoLideranca",
                "DescricaoLideranca",
                "NomeBancada",
                "NomeBloco",
                "DataInicio",
                "DataFim",
            ),
        )
        title = _first(
            leadership,
            "DescricaoTipoLideranca",
            "DescricaoLideranca",
            "TipoLideranca",
            "NomeLideranca",
        )
        if not key or not title:
            continue
        _post(
            source=source,
            source_key=f"{key}:member:{external_id}",
            house="senado",
            term=term,
            title=title,
            record=leadership,
            fallback_url=_url(leadership, leadership_url),
        )
        counts["posts"] += 1

    post_url = f"{base_url}/senador/{external_id}/cargos"
    for post in posts:
        key = _provider_key(
            "cargo",
            post,
            ("CodigoCargo", "IdCargo", "idCargo"),
            (
                "DescricaoCargo",
                "NomeCargo",
                "Cargo",
                "NomeOrgao",
                "DataInicio",
                "DataFim",
            ),
        )
        title = _first(post, "DescricaoCargo", "NomeCargo", "Cargo", "descricaoCargo")
        if not key or not title:
            continue
        _post(
            source=source,
            source_key=f"{key}:member:{external_id}",
            house="senado",
            term=term,
            title=title,
            record=post,
            fallback_url=_url(post, post_url),
        )
        counts["posts"] += 1
    return counts


@transaction.atomic
def persist_official_relationships(*, term: ParliamentarianTerm, client) -> dict[str, int]:
    """Persist one selected current term's official relationships.

    The caller owns the per-parliamentarian failure boundary.  Fetches happen
    before writes so a provider failure does not leave a half-written snapshot.
    """
    if term.house == "camara":
        return _persist_camara(term, client)
    if term.house == "senado":
        return _persist_senado(term, client)
    raise ValueError(f"unsupported house: {term.house}")


def persist_senado_fronts(*, fronts, terms: list[ParliamentarianTerm]) -> dict[str, int]:
    """Persist one scraped Senate-front snapshot using current term identities only."""
    current_senators = {}
    for term in terms:
        if term.house == "senado":
            current_senators.setdefault(term.external_id, term)

    counts = {"processed": 0, "failed": 0, "memberships": 0}
    for front in fronts:
        try:
            with transaction.atomic():
                record = {
                    "url": front.council_url,
                    "status": front.status,
                }
                representative = next(iter(current_senators.values()), None)
                caucus = _caucus(
                    source="senado",
                    source_key=str(front.codcol),
                    house="senado",
                    kind=CaucusKind.FRENTE,
                    name=front.name,
                    term=representative,
                    record=record,
                    fallback_url=front.council_url,
                )
                for member in front.members:
                    if member.house != "senado":
                        continue
                    term = current_senators.get(member.external_id)
                    if term is None:
                        continue
                    _caucus_membership(
                        source="senado",
                        source_key=(
                            f"{front.codcol}:member:{member.house}:{member.external_id}"
                        ),
                        caucus=caucus,
                        term=term,
                        record={"role": member.role, "url": member.profile_url},
                        fallback_url=front.composition_url,
                    )
                    counts["memberships"] += 1
                counts["processed"] += 1
        except Exception:
            counts["failed"] += 1
    return counts
