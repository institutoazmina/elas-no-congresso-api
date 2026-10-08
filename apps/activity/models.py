from django.db import models

from apps.committees.models import Committee
from apps.core.enums import AttendanceStatus, House, VoteChoice
from apps.legislatures.models import Legislature, Parliamentarian, Party
from apps.propositions.models import Proposition


class Vote(models.Model):
    proposition = models.ForeignKey(
        Proposition,
        verbose_name="Proposição",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="votes",
    )
    committee = models.ForeignKey(
        Committee,
        verbose_name="Comissão",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="votes",
    )
    held_at = models.DateTimeField(verbose_name="Realizada em")
    scope = models.TextField(verbose_name="Âmbito")
    summary = models.TextField(verbose_name="Resumo", null=True, blank=True)
    result = models.TextField(verbose_name="Resultado", null=True, blank=True)
    yes_count = models.IntegerField(verbose_name="Votos a favor", null=True, blank=True)
    no_count = models.IntegerField(verbose_name="Votos contra", null=True, blank=True)
    abstain_count = models.IntegerField(verbose_name="Abstenções", null=True, blank=True)

    class Meta:
        verbose_name = "Votação"
        verbose_name_plural = "Votações"
        db_table = "votes"
        indexes = [
            models.Index(fields=["proposition", "-held_at"], name="idx_votes_prop"),
            models.Index(fields=["-held_at"], name="idx_votes_date"),
        ]


class VoteRecord(models.Model):
    vote = models.ForeignKey(
        Vote, verbose_name="Votação", on_delete=models.CASCADE, related_name="records"
    )
    parliamentarian = models.ForeignKey(
        Parliamentarian,
        verbose_name="Parlamentar",
        on_delete=models.CASCADE,
        related_name="vote_records",
    )
    choice = models.CharField(verbose_name="Voto", max_length=15, choices=VoteChoice.choices)
    party = models.ForeignKey(
        Party,
        verbose_name="Partido",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vote_records",
    )
    recorded_at = models.DateTimeField(verbose_name="Registrado em", auto_now_add=True)

    class Meta:
        verbose_name = "Voto parlamentar"
        verbose_name_plural = "Votos parlamentares"
        db_table = "vote_records"
        constraints = [
            models.UniqueConstraint(fields=["vote", "parliamentarian"], name="vote_records_pk")
        ]
        indexes = [
            models.Index(fields=["parliamentarian", "choice"], name="idx_vr_parl"),
            models.Index(fields=["party", "choice"], name="idx_vr_party_choice"),
        ]


class PlenarySession(models.Model):
    house = models.CharField(verbose_name="Casa legislativa", max_length=10, choices=House.choices)
    held_at = models.DateTimeField(verbose_name="Realizada em")
    kind = models.TextField(verbose_name="Tipo", null=True, blank=True)
    legislature = models.ForeignKey(
        Legislature,
        verbose_name="Legislatura",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="plenary_sessions",
    )

    class Meta:
        verbose_name = "Sessão plenária"
        verbose_name_plural = "Sessões plenárias"
        db_table = "plenary_sessions"
        indexes = [models.Index(fields=["house", "-held_at"], name="idx_sessions_date")]


class AttendanceRecord(models.Model):
    session = models.ForeignKey(
        PlenarySession, verbose_name="Sessão", on_delete=models.CASCADE, related_name="attendance"
    )
    parliamentarian = models.ForeignKey(
        Parliamentarian,
        verbose_name="Parlamentar",
        on_delete=models.CASCADE,
        related_name="attendance_records",
    )
    status = models.CharField(
        verbose_name="Situação", max_length=15, choices=AttendanceStatus.choices
    )

    class Meta:
        verbose_name = "Registro de presença"
        verbose_name_plural = "Registros de presença"
        db_table = "attendance_records"
        constraints = [
            models.UniqueConstraint(
                fields=["session", "parliamentarian"], name="attendance_records_pk"
            )
        ]
        indexes = [models.Index(fields=["parliamentarian", "status"], name="idx_attendance_parl")]


class Speech(models.Model):
    parliamentarian = models.ForeignKey(
        Parliamentarian,
        verbose_name="Parlamentar",
        on_delete=models.CASCADE,
        related_name="speeches",
    )
    proposition = models.ForeignKey(
        Proposition,
        verbose_name="Proposição",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="speeches",
    )
    delivered_at = models.DateTimeField(verbose_name="Proferido em")
    content = models.TextField(verbose_name="Conteúdo")
    summary = models.TextField(verbose_name="Resumo", null=True, blank=True)
    source_url = models.TextField(verbose_name="URL da fonte", null=True, blank=True)

    class Meta:
        verbose_name = "Discurso"
        verbose_name_plural = "Discursos"
        db_table = "speeches"
        indexes = [
            models.Index(fields=["parliamentarian", "-delivered_at"], name="idx_speeches_parl"),
        ]
