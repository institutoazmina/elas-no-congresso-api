from datetime import date

import pytest

from apps.legislatures.models import Legislature

pytestmark = pytest.mark.django_db


def test_seed_completo_e_sem_sobreposicao():
    legs = list(Legislature.objects.order_by("number"))

    assert [leg.number for leg in legs] == list(range(1, 61))
    assert legs[0].start_date == date(1826, 5, 6)
    assert legs[-1].end_date == date(2039, 1, 31)

    for anterior, atual in zip(legs, legs[1:], strict=False):
        assert anterior.end_date < atual.start_date, (
            f"{anterior.number}ª sobrepõe a {atual.number}ª"
        )


def test_for_date():
    assert Legislature.for_date(date(2024, 3, 1)).number == 57
    assert Legislature.for_date(date(2023, 2, 1)).number == 57  # limites inclusivos
    assert Legislature.for_date(date(2023, 1, 31)).number == 56
    assert Legislature.for_date(date(1940, 1, 1)) is None  # Estado Novo
