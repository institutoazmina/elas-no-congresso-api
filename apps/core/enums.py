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
