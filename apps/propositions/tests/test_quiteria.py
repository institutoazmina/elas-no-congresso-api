from datetime import date

import pytest

from apps.core.enums import House
from apps.propositions.models import Proposition
from apps.propositions.quiteria import THEME_INDEX_TO_CATEGORY, build_input, format_markdown


@pytest.mark.django_db
def test_build_input_reproduces_the_training_format():
    proposition = Proposition.objects.create(
        house=House.CAMARA,
        external_id=9001,
        type_code="PL",
        number_label="PL 1/2026",
        number=1,
        year=2026,
        presented_at=date(2026, 1, 1),
        ementa="Ementa de fallback.",
        full_text="## Texto  com\\_ marcação.\nTexto com marcação.\n<!-- comentário -->",
    )

    assert format_markdown(proposition.full_text) == "Texto com marcação."
    assert build_input(proposition) == ("Partido: ; Genero: ; UF: ; Conteúdo: Texto com marcação.")


def test_theme_mapping_matches_the_training_repository():
    assert THEME_INDEX_TO_CATEGORY == {
        0: "direitos_sexuais_reprodutivos",
        1: "educacao_cultura",
        2: "familia_parentalidade",
        3: "igualdade_antidiscriminacao",
        4: "infancia_adolescencia",
        5: "lgbtqiapn",
        6: "participacao_politica",
        7: "saude",
        8: "trabalho_economia_cuidado",
        9: "violencias_de_genero",
    }
