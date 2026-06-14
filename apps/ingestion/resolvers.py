"""Resolução de entidades normalizadas a partir dos dados brutos de coleta.

Decisão de projeto: resolver autores agora (não adiar). Estratégia:
  1. Se há external_id e já existe um mandato (ParliamentarianTerm) para a casa
     → reaproveita o Parlamentar.
  2. Se o autor é institucional (Poder Executivo, comissão, casa legislativa…)
     → InstitutionalAuthor.get_or_create.
  3. Caso seja pessoa sem mandato conhecido → cria Parlamentar mínimo pelo nome.
     (A sincronização completa de mandatos/legislaturas é um processo separado.)
"""

import logging

from apps.legislatures.models import (
    InstitutionalAuthor,
    Parliamentarian,
    ParliamentarianTerm,
)

logger = logging.getLogger(__name__)

# Palavras que indicam autoria institucional (não-parlamentar).
_INSTITUTIONAL_HINTS = (
    "poder executivo",
    "comissão",
    "comissao",
    "senado federal",
    "câmara dos deputados",
    "camara dos deputados",
    "congresso nacional",
    "mesa",
    "bancada",
    "presidência",
    "presidencia",
    "tribunal",
    "procuradoria",
)


def _is_institutional(name: str, kind: str) -> bool:
    blob = f"{name} {kind}".lower()
    return any(h in blob for h in _INSTITUTIONAL_HINTS)


def resolve_author(author: dict, house: str) -> tuple[Parliamentarian | None, InstitutionalAuthor | None]:
    """Resolve um autor normalizado para (Parliamentarian, InstitutionalAuthor).

    Exatamente um dos dois é não-nulo (satisfaz o CheckConstraint de
    proposition_authors_at_least_one_author).
    """
    name = (author.get("name") or "").strip()
    kind = (author.get("kind") or "").strip()
    external_id = author.get("external_id")
    gender = author.get("gender")

    if not name:
        return None, None

    if _is_institutional(name, kind):
        inst, _ = InstitutionalAuthor.objects.get_or_create(
            name=name, defaults={"kind": kind or "instituição"}
        )
        return None, inst

    if external_id is not None:
        term = (
            ParliamentarianTerm.objects.filter(house=house, external_id=external_id)
            .select_related("parliamentarian")
            .first()
        )
        if term:
            _backfill_gender(term.parliamentarian, gender)
            return term.parliamentarian, None

    # Pessoa sem mandato conhecido: cria parlamentar mínimo pelo nome.
    parl, created = Parliamentarian.objects.get_or_create(
        full_name=name, defaults={"gender": gender}
    )
    if created:
        logger.info("Parlamentar mínimo criado por coleta: %s (casa=%s)", name, house)
    else:
        _backfill_gender(parl, gender)
    return parl, None


def _backfill_gender(parl: Parliamentarian, gender: str | None) -> None:
    """Preenche o sexo de um parlamentar já existente quando ainda estiver vazio."""
    if gender and not parl.gender:
        parl.gender = gender
        parl.save(update_fields=["gender"])
