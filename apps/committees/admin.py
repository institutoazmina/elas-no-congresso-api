from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import (
    Caucus,
    CaucusMembership,
    Committee,
    CommitteeMembership,
)


@admin.register(Committee)
class CommitteeAdmin(ModelAdmin):
    list_display = ["acronym", "house", "name", "kind", "is_active"]
    list_filter = ["house", "is_active"]
    search_fields = ["acronym", "name"]


@admin.register(CommitteeMembership)
class CommitteeMembershipAdmin(ModelAdmin):
    list_display = ["committee", "parliamentarian", "role", "start_date", "end_date"]
    autocomplete_fields = ["committee", "parliamentarian"]


@admin.register(Caucus)
class CaucusAdmin(ModelAdmin):
    list_display = ["name", "kind", "legislature"]
    list_filter = ["kind"]
    search_fields = ["name"]


@admin.register(CaucusMembership)
class CaucusMembershipAdmin(ModelAdmin):
    list_display = ["caucus", "parliamentarian", "role", "start_date", "end_date"]
    autocomplete_fields = ["caucus", "parliamentarian"]
