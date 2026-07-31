from django.db import models


class House(models.TextChoices):
    CAMARA = "camara", "Câmara"
    SENADO = "senado", "Senado"


class Gender(models.TextChoices):
    F = "F", "Feminino"
    M = "M", "Masculino"
    NB = "NB", "Não-binário"
    NI = "NI", "Não informado"


class ContactChannel(models.TextChoices):
    EMAIL = "email", "E-mail"
    PHONE = "phone", "Telefone"
    ADDRESS = "address", "Endereço"
    WEBSITE = "website", "Website"
    TWITTER = "twitter", "Twitter/X"
    INSTAGRAM = "instagram", "Instagram"
    FACEBOOK = "facebook", "Facebook"
    YOUTUBE = "youtube", "YouTube"
    TIKTOK = "tiktok", "TikTok"
    LINKEDIN = "linkedin", "LinkedIn"


class LegalNormType(models.TextChoices):
    CONSTITUICAO = "constituicao", "Constituição"
    EMENDA_CONSTITUCIONAL = "emenda_constitucional", "Emenda Constitucional"
    LEI_COMPLEMENTAR = "lei_complementar", "Lei Complementar"
    LEI_ORDINARIA = "lei_ordinaria", "Lei Ordinária"
    MEDIDA_PROVISORIA = "medida_provisoria", "Medida Provisória"
    DECRETO = "decreto", "Decreto"
    DECRETO_LEI = "decreto_lei", "Decreto-Lei"
    CODIGO = "codigo", "Código"


class AmendRelationType(models.TextChoices):
    ALTERA = "altera", "Altera"
    REVOGA = "revoga", "Revoga"
    REGULAMENTA = "regulamenta", "Regulamenta"
    REFERENCIA = "referencia", "Referência"


class VoteChoice(models.TextChoices):
    YES = "yes", "Sim"
    NO = "no", "Não"
    ABSTAIN = "abstain", "Abstenção"
    ABSENT = "absent", "Ausente"
    OBSTRUCTION = "obstruction", "Obstrução"


class AttendanceStatus(models.TextChoices):
    PRESENT = "present", "Presente"
    ABSENT = "absent", "Ausente"
    JUSTIFIED = "justified", "Justificado"
    ON_MISSION = "on_mission", "Em missão"


class CommitteeStage(models.TextChoices):
    PLANNED = "planned", "Prevista"
    CURRENT = "current", "Atual"
    PASSED = "passed", "Encerrada"
    APPROVED = "approved", "Aprovada"
    REJECTED = "rejected", "Rejeitada"


class CaucusKind(models.TextChoices):
    FRENTE = "frente", "Frente Parlamentar"
    BANCADA = "bancada", "Bancada"
    BLOCO = "bloco", "Bloco"


class RelationType(models.TextChoices):
    APPENDED = "appended", "Apensada"
    SIMILAR = "similar", "Similar"
    PREDECESSOR = "predecessor", "Predecessora"
    SUCCESSOR = "successor", "Sucessora"


class HumanRelevance(models.TextChoices):
    MUITO_RELEVANTE = "muito_relevante", "Muito relevante"
    POUCO_RELEVANTE = "pouco_relevante", "Pouco relevante"
    RELEVANTE = "relevante", "Relevante"
    SAIU_DE_PAUTA = "saiu_de_pauta", "Saiu de pauta"


class PropositionCategory(models.TextChoices):
    """Taxonomia editorial fechada ("Categorias 2026") das anotações humanas.

    Substitui o antigo `human_theme` (texto livre, 107 variantes com duplicatas
    de caixa). Toda anotação é obrigatoriamente uma destas — o texto original
    ficou preservado em `legacy_theme`, fora dos formulários.
    """

    VIOLENCIAS_DE_GENERO = "violencias_de_genero", "Violências de Gênero"
    TRABALHO_ECONOMIA_CUIDADO = (
        "trabalho_economia_cuidado", "Trabalho, Economia, Cuidado e Proteção Social"
    )
    DIREITOS_SEXUAIS_REPRODUTIVOS = (
        "direitos_sexuais_reprodutivos", "Direitos Sexuais e Reprodutivos"
    )
    PARTICIPACAO_POLITICA = (
        "participacao_politica", "Participação Política e Institucionalidade"
    )
    LGBTQIAPN = "lgbtqiapn", "LGBTQIAPN+"
    SAUDE = "saude", "Saúde"
    EDUCACAO_CULTURA = "educacao_cultura", "Educação e Cultura"
    FAMILIA_PARENTALIDADE = (
        "familia_parentalidade", "Família, Parentalidade e Relações Civis"
    )
    INFANCIA_ADOLESCENCIA = "infancia_adolescencia", "Infância e Adolescência"
    IGUALDADE_ANTIDISCRIMINACAO = (
        "igualdade_antidiscriminacao", "Igualdade e Antidiscriminação"
    )
