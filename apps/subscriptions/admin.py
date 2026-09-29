from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from unfold.admin import ModelAdmin

from .models import Subscription
from .service import ast_matches_proposition
from .tasks import send_test_alert_email


class SendTestAlertForm(forms.Form):
    proposition_id = forms.IntegerField(
        label="ID da proposição",
        min_value=1,
        widget=forms.NumberInput(
            attrs={
                "class": "border border-base-200 bg-white dark:bg-base-900 dark:border-base-700 "
                "rounded-default px-3 py-2 w-full",
            }
        ),
    )
    ast = forms.JSONField(
        label="Critérios (AST JSON)",
        widget=forms.Textarea(
            attrs={
                "rows": 14,
                "class": "border border-base-200 bg-white dark:bg-base-900 dark:border-base-700 "
                "rounded-default px-3 py-2 w-full font-mono",
            }
        ),
        help_text="Os critérios são usados apenas neste teste e não serão salvos na inscrição.",
    )
    confirm_send = forms.BooleanField(
        label="Confirmo que este e-mail de teste será enviado ao endereço desta inscrição."
    )

    def clean_ast(self):
        ast = self.cleaned_data["ast"]
        from .compiler import ast_to_tsquery

        try:
            ast_to_tsquery(ast)
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise forms.ValidationError(f"Critério inválido: {exc}") from exc
        return ast


@admin.register(Subscription)
class SubscriptionAdmin(ModelAdmin):
    change_form_template = "admin/subscriptions/subscription/change_form.html"
    list_display = ["email", "is_active", "needs_revalidation", "created_at", "confirmed_at"]
    list_filter = ["is_active", "needs_revalidation"]
    search_fields = ["email"]
    readonly_fields = ["confirm_token", "unsubscribe_token", "created_at", "confirmed_at", "query"]
    ordering = ["-created_at"]

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/send-test-alert/",
                self.admin_site.admin_view(self.send_test_alert),
                name="subscriptions_subscription_send_test_alert",
            ),
        ]
        return custom_urls + urls

    def send_test_alert(self, request, object_id):
        if not self.has_change_permission(request):
            raise PermissionDenied

        subscription = get_object_or_404(Subscription, pk=object_id)
        if not subscription.is_active:
            self.message_user(
                request,
                "Somente inscrições confirmadas podem receber um alerta de teste.",
                messages.ERROR,
            )
            return redirect("admin:subscriptions_subscription_change", subscription.pk)

        initial = {"ast": subscription.ast}
        if request.method == "POST":
            form = SendTestAlertForm(request.POST)
            if form.is_valid():
                from apps.propositions.models import Proposition

                proposition = Proposition.objects.filter(
                    pk=form.cleaned_data["proposition_id"]
                ).first()
                if proposition is None:
                    form.add_error("proposition_id", "Proposição não encontrada.")
                elif not ast_matches_proposition(form.cleaned_data["ast"], proposition.pk):
                    form.add_error(
                        "ast",
                        "Estes critérios não correspondem à proposição escolhida; nenhum e-mail foi enviado.",
                    )
                else:
                    task = send_test_alert_email.delay(subscription.pk, proposition.pk)
                    self.message_user(
                        request,
                        f"Alerta de teste enfileirado. ID da tarefa: {task.id}",
                        messages.SUCCESS,
                    )
                    return redirect("admin:subscriptions_subscription_change", subscription.pk)
        else:
            form = SendTestAlertForm(initial=initial)

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "subscription": subscription,
            "form": form,
            "title": "Enviar alerta de teste",
            "subtitle": None,
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(
            request, "admin/subscriptions/subscription/send_test_alert.html", context
        )

    def render_change_form(self, request, context, *args, **kwargs):
        subscription = context.get("original")
        if (
            subscription
            and subscription.is_active
            and self.has_change_permission(request, subscription)
        ):
            context["send_test_alert_url"] = reverse(
                "admin:subscriptions_subscription_send_test_alert", args=[subscription.pk]
            )
        return super().render_change_form(request, context, *args, **kwargs)
