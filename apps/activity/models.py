from django.db import models

from apps.committees.models import Committee
from apps.core.enums import AttendanceStatus, House, VoteChoice
from apps.legislatures.models import Legislature, Parliamentarian, Party
from apps.propositions.models import Proposition


class Vote(models.Model):
    proposition = models.ForeignKey(
        Proposition, on_delete=models.SET_NULL, null=True, blank=True, related_name="votes"
    )
    committee = models.ForeignKey(
        Committee, on_delete=models.SET_NULL, null=True, blank=True, related_name="votes"
    )
    held_at = models.DateTimeField()
    scope = models.TextField()
    summary = models.TextField(null=True, blank=True)
    result = models.TextField(null=True, blank=True)
    yes_count = models.IntegerField(null=True, blank=True)
    no_count = models.IntegerField(null=True, blank=True)
    abstain_count = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "votes"
        indexes = [
            models.Index(fields=["proposition", "-held_at"], name="idx_votes_prop"),
            models.Index(fields=["-held_at"], name="idx_votes_date"),
        ]


class VoteRecord(models.Model):
    vote = models.ForeignKey(Vote, on_delete=models.CASCADE, related_name="records")
    parliamentarian = models.ForeignKey(
        Parliamentarian, on_delete=models.CASCADE, related_name="vote_records"
    )
    choice = models.CharField(max_length=15, choices=VoteChoice.choices)
    party = models.ForeignKey(
        Party, on_delete=models.SET_NULL, null=True, blank=True, related_name="vote_records"
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "vote_records"
        constraints = [
            models.UniqueConstraint(fields=["vote", "parliamentarian"], name="vote_records_pk")
        ]
        indexes = [
            models.Index(fields=["parliamentarian", "choice"], name="idx_vr_parl"),
            models.Index(fields=["party", "choice"], name="idx_vr_party_choice"),
        ]


class PlenarySession(models.Model):
    house = models.CharField(max_length=10, choices=House.choices)
    held_at = models.DateTimeField()
    kind = models.TextField(null=True, blank=True)
    legislature = models.ForeignKey(
        Legislature, on_delete=models.SET_NULL, null=True, blank=True, related_name="plenary_sessions"
    )

    class Meta:
        db_table = "plenary_sessions"
        indexes = [models.Index(fields=["house", "-held_at"], name="idx_sessions_date")]


class AttendanceRecord(models.Model):
    session = models.ForeignKey(PlenarySession, on_delete=models.CASCADE, related_name="attendance")
    parliamentarian = models.ForeignKey(
        Parliamentarian, on_delete=models.CASCADE, related_name="attendance_records"
    )
    status = models.CharField(max_length=15, choices=AttendanceStatus.choices)

    class Meta:
        db_table = "attendance_records"
        constraints = [
            models.UniqueConstraint(fields=["session", "parliamentarian"], name="attendance_records_pk")
        ]
        indexes = [
            models.Index(fields=["parliamentarian", "status"], name="idx_attendance_parl")
        ]


class Speech(models.Model):
    parliamentarian = models.ForeignKey(
        Parliamentarian, on_delete=models.CASCADE, related_name="speeches"
    )
    proposition = models.ForeignKey(
        Proposition, on_delete=models.SET_NULL, null=True, blank=True, related_name="speeches"
    )
    delivered_at = models.DateTimeField()
    content = models.TextField()
    summary = models.TextField(null=True, blank=True)
    source_url = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "speeches"
        indexes = [
            models.Index(fields=["parliamentarian", "-delivered_at"], name="idx_speeches_parl"),
        ]
