"""Filtro de relevância temática — portado 1:1 do elasnocongressobot.

Roda sobre a ementa ANTES de descer nos saltos caros (autores, inteiro teor),
para coletar apenas proposições relevantes ao tema de gênero/direitos das mulheres.
"""

import re

# Termos relevantes por si só.
_PATTERN_STANDALONE = re.compile(
    r"\b(ABORTAMENTO|ABORTO|ABUSO SEXUAL|AMAMENTAÇÃO|ASSÉDIO|ASSÉDIO SEXUAL|BEBÊ|CASAMENTO|"
    r"CASAMENTO INFANTIL|CONCEPÇÃO|CONTRACEPÇÃO|CONTRACEPTIVO|CRECHE|CRIANÇA|CYTOTEC|"
    r"DIREITO À VIDA|DIREITO DOS HOMENS|DIREITO REPRODUTIVO|DIREITOS REPRODUTIVOS|DIVÓRCIO|"
    r"DOMÉSTICA|EDUCAÇÃO DOMICILIAR|EDUCAÇÃO INFANTIL|EDUCAÇÃO SEXUAL|ESCOLA SEM PARTIDO|"
    r"ESTUPRO|ESTUPRO DE VULNERÁVEL|EXPLORAÇÃO SEXUAL|FEMINICÍDIO|FEMININO|FEMINISMO|FETO|"
    r"GÊNERO|GESTAÇÃO|GESTANTE|GRAVIDEZ|GUARDA DE FILHOS|GUARDA DOS FILHOS|HOMESCHOOLING|"
    r"HOMICÍDIO DE MULHER|HOMOSSEXUAL|IDENTIDADE DE GÊNERO|IDEOLOGIA DE GÊNERO|IGUALDADE|"
    r"IGUALDADE DE GÊNERO|INTERRUPÇÃO DA GESTAÇÃO|INTERRUPÇÃO DA GRAVIDEZ|LÉSBICA|"
    r"LICENÇA MATERNIDADE|MACHISMO|MÃE|MARIA DA PENHA|MATERNIDADE|MIFEPRISTONE|MISOPROSTOL|"
    r"MORTE DE MULHER|MUDANÇA DE SEXO|MULHER|MULHER NEGRA|MULHER TRANS|MULHERES INDÍGENAS|"
    r"MULHERES NEGRAS|MULHERES QUILOMBOLAS|MULHERES TRANS|NASCITURO|NEGRA|ORIENTAÇÃO SEXUAL|"
    r"PARTO|PROSTITUIÇÃO|READEQUAÇÃO SEXUAL|SEXO|SEXUALIDADE|TRABALHO DOMÉSTICO|TRANS|TRANSEX|"
    r"TRANSGEN|TRANSEXUAL|TRANSEXUALIDADE|ÚTERO|VIOLÊNCIA CONTRA A MULHER|VIOLÊNCIA DE GÊNERO|"
    r"VIOLÊNCIA POLÍTICA DE GÊNERO|VIOLÊNCIA DOMÉSTICA|VIOLÊNCIA OBSTÉTRICA|VIOLÊNCIA SEXUAL|"
    r"SEXUAL)\b",
    re.IGNORECASE,
)

# Termos relevantes só quando combinados com "mulher".
_PATTERN_COMBINED = re.compile(
    r"(?=.*\bmulher\b).*\b(COTAS|TRABALHO|RAÇA|PARTICIPAÇÃO POLÍTICA|RACIAL|POLÍTICA|RACISMO|"
    r"RELIGIÃO|EDUCAÇÃO RELIGIOSA|DEUS)\b",
    re.IGNORECASE,
)


def assert_theme(*fields: str | None) -> dict:
    """Avalia se os campos textuais dados são relevantes ao tema.

    Retorna ``{"row_relevant": bool, "temas": list[str]}``.
    """
    text = " ".join(f or "" for f in fields)
    if not text.strip():
        return {"row_relevant": False, "temas": []}

    matches = _PATTERN_STANDALONE.findall(text) + _PATTERN_COMBINED.findall(text)
    return {"row_relevant": len(matches) > 0, "temas": matches}
