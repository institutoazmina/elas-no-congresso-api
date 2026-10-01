import csv

import pytest
from django.core.management import call_command

from apps.legislatures.models import Legislature, Parliamentarian, ParliamentarianTerm, Party
from apps.legislatures.religion_mapper import map_religion_rows


def test_mapper_preserves_source_labels_and_excludes_conflicts():
    assert map_religion_rows(
        [
            {"ID_Camara": "123", "Identidade Religiosa": "Sem Religião"},
            {"ID_Camara": "456", "Identidade Religiosa": "Não identificada"},
        ]
    ).values == {123: "Sem Religião", 456: "Não identificada"}

    result = map_religion_rows(
        [
            {"ID_Camara": "123", "Identidade Religiosa": "Católica"},
            {"ID_Camara": "123", "Identidade Religiosa": "Evangélica"},
        ]
    )
    assert result.values == {}
    assert result.conflicting_ids == {123}


@pytest.mark.django_db
def test_import_command_updates_camara_by_external_id_with_sql(tmp_path):
    legislature, _ = Legislature.objects.update_or_create(
        number=57,
        defaults={"start_date": "2023-02-01", "end_date": "2027-01-31"},
    )
    party = Party.objects.create(acronym="PT", name="Partido dos Trabalhadores")
    chamber_member = Parliamentarian.objects.create(full_name="Pessoa Câmara")
    senate_member = Parliamentarian.objects.create(full_name="Pessoa Senado")
    ParliamentarianTerm.objects.create(
        parliamentarian=chamber_member,
        legislature_number=legislature,
        party=party,
        house="camara",
        role="Deputada",
        state="SP",
        external_id=220593,
        start_date="2023-02-01",
    )
    ParliamentarianTerm.objects.create(
        parliamentarian=senate_member,
        legislature_number=legislature,
        party=party,
        house="senado",
        role="Senadora",
        state="SP",
        external_id=220593,
        start_date="2023-02-01",
    )
    csv_path = tmp_path / "religioes.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=["ID_Camara", "Identidade Religiosa"])
        writer.writeheader()
        writer.writerow({"ID_Camara": 220593, "Identidade Religiosa": "Evangélica"})
        writer.writerow({"ID_Camara": 999999, "Identidade Religiosa": "Católica"})

    call_command("import_parliamentarian_religions", csv_path=csv_path)

    chamber_member.refresh_from_db()
    senate_member.refresh_from_db()
    assert chamber_member.religion == "Evangélica"
    assert senate_member.religion is None


@pytest.mark.django_db
def test_import_command_dry_run_does_not_write(tmp_path):
    legislature, _ = Legislature.objects.update_or_create(
        number=57,
        defaults={"start_date": "2023-02-01", "end_date": "2027-01-31"},
    )
    party = Party.objects.create(acronym="PSOL", name="Partido Socialismo e Liberdade")
    parliamentarian = Parliamentarian.objects.create(full_name="Pessoa Câmara")
    ParliamentarianTerm.objects.create(
        parliamentarian=parliamentarian,
        legislature_number=legislature,
        party=party,
        house="camara",
        role="Deputada",
        state="RJ",
        external_id=204528,
        start_date="2023-02-01",
    )
    csv_path = tmp_path / "religioes.csv"
    csv_path.write_text(
        "ID_Camara,Identidade Religiosa\n204528,NÃO IDENTIFICADA\n", encoding="utf-8"
    )

    call_command("import_parliamentarian_religions", csv_path=csv_path, dry_run=True)

    parliamentarian.refresh_from_db()
    assert parliamentarian.religion is None
