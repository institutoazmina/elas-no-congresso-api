from django.db import migrations

# Frozen original seed: later changes must use a new data migration.
_DEFAULT_STANDALONE = [
    "ABORTAMENTO",
    "ABORTO",
    "ABUSO SEXUAL",
    "AMAMENTAÇÃO",
    "ASSÉDIO",
    "ASSÉDIO SEXUAL",
    "BEBÊ",
    "CASAMENTO",
    "CASAMENTO INFANTIL",
    "CONCEPÇÃO",
    "CONTRACEPÇÃO",
    "CONTRACEPTIVO",
    "CRECHE",
    "CRIANÇA",
    "CYTOTEC",
    "DIREITO À VIDA",
    "DIREITO DOS HOMENS",
    "DIREITO REPRODUTIVO",
    "DIREITOS REPRODUTIVOS",
    "DIVÓRCIO",
    "DOMÉSTICA",
    "EDUCAÇÃO DOMICILIAR",
    "EDUCAÇÃO INFANTIL",
    "EDUCAÇÃO SEXUAL",
    "ESCOLA SEM PARTIDO",
    "ESTUPRO",
    "ESTUPRO DE VULNERÁVEL",
    "EXPLORAÇÃO SEXUAL",
    "FEMINICÍDIO",
    "FEMININO",
    "FEMINISMO",
    "FETO",
    "GÊNERO",
    "GESTAÇÃO",
    "GESTANTE",
    "GRAVIDEZ",
    "GUARDA DE FILHOS",
    "GUARDA DOS FILHOS",
    "HOMESCHOOLING",
    "HOMICÍDIO DE MULHER",
    "HOMOSSEXUAL",
    "IDENTIDADE DE GÊNERO",
    "IDEOLOGIA DE GÊNERO",
    "IGUALDADE",
    "IGUALDADE DE GÊNERO",
    "INTERRUPÇÃO DA GESTAÇÃO",
    "INTERRUPÇÃO DA GRAVIDEZ",
    "LÉSBICA",
    "LICENÇA MATERNIDADE",
    "MACHISMO",
    "MÃE",
    "MARIA DA PENHA",
    "MATERNIDADE",
    "MIFEPRISTONE",
    "MISOPROSTOL",
    "MORTE DE MULHER",
    "MUDANÇA DE SEXO",
    "MULHER",
    "MULHER NEGRA",
    "MULHER TRANS",
    "MULHERES INDÍGENAS",
    "MULHERES NEGRAS",
    "MULHERES QUILOMBOLAS",
    "MULHERES TRANS",
    "NASCITURO",
    "NEGRA",
    "ORIENTAÇÃO SEXUAL",
    "PARTO",
    "PROSTITUIÇÃO",
    "READEQUAÇÃO SEXUAL",
    "SEXO",
    "SEXUALIDADE",
    "TRABALHO DOMÉSTICO",
    "TRANS",
    "TRANSEX",
    "TRANSGEN",
    "TRANSEXUAL",
    "TRANSEXUALIDADE",
    "ÚTERO",
    "VIOLÊNCIA CONTRA A MULHER",
    "VIOLÊNCIA DE GÊNERO",
    "VIOLÊNCIA POLÍTICA DE GÊNERO",
    "VIOLÊNCIA DOMÉSTICA",
    "VIOLÊNCIA OBSTÉTRICA",
    "VIOLÊNCIA SEXUAL",
    "SEXUAL",
]
_DEFAULT_COMBINED = [
    "COTAS",
    "TRABALHO",
    "RAÇA",
    "PARTICIPAÇÃO POLÍTICA",
    "RACIAL",
    "POLÍTICA",
    "RACISMO",
    "RELIGIÃO",
    "EDUCAÇÃO RELIGIOSA",
    "DEUS",
]


def seed(apps, schema_editor):

    RelevanceTerm = apps.get_model("ingestion", "RelevanceTerm")
    rows = [RelevanceTerm(term=t, mode="standalone") for t in _DEFAULT_STANDALONE]
    rows += [RelevanceTerm(term=t, mode="combined") for t in _DEFAULT_COMBINED]
    RelevanceTerm.objects.bulk_create(rows, ignore_conflicts=True)


def unseed(apps, schema_editor):
    RelevanceTerm = apps.get_model("ingestion", "RelevanceTerm")
    RelevanceTerm.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("ingestion", "0002_relevanceterm")]

    operations = [migrations.RunPython(seed, unseed)]
