from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Subscription


@admin.register(Subscription)
class SubscriptionAdmin(ModelAdmin):
    list_display = ["email", "is_active", "needs_revalidation", "created_at", "confirmed_at"]
    list_filter = ["is_active", "needs_revalidation"]
    search_fields = ["email"]
    readonly_fields = ["confirm_token", "unsubscribe_token", "created_at", "confirmed_at", "query"]
    ordering = ["-created_at"]
