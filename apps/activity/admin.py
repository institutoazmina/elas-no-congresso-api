from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import PlenarySession, Speech, Vote, VoteRecord


@admin.register(Vote)
class VoteAdmin(ModelAdmin):
    list_display = ["proposition", "committee", "held_at", "result", "yes_count", "no_count"]
    search_fields = ["proposition__number_label", "committee__name"]
    autocomplete_fields = ["proposition", "committee"]


@admin.register(VoteRecord)
class VoteRecordAdmin(ModelAdmin):
    list_display = ["vote", "parliamentarian", "choice", "party"]
    list_filter = ["choice"]
    autocomplete_fields = ["vote", "parliamentarian"]


@admin.register(PlenarySession)
class PlenarySessionAdmin(ModelAdmin):
    list_display = ["house", "held_at", "kind", "legislature"]
    list_filter = ["house"]


@admin.register(Speech)
class SpeechAdmin(ModelAdmin):
    list_display = ["parliamentarian", "delivered_at", "proposition"]
    search_fields = ["content", "summary"]
    autocomplete_fields = ["parliamentarian", "proposition"]
