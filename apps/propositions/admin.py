from django.contrib import admin, messages
from django.contrib.admin.utils import NestedObjects, quote
from django.core.exceptions import PermissionDenied
from django.db import router
from django.db.models import QuerySet
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import NoReverseMatch, path, reverse
from django.utils.html import format_html
from django.utils.text import capfirst
from unfold.admin import ModelAdmin, TabularInline

from apps.ingestion.sync import enqueue_manual_links

from .admin_cache import ActivityCacheAdminMixin
from .admin_forms import PropositionLinksForm
from .models import (
    AssessmentOrganization,
    ClassificationRequest,
    IgnoredProposition,
    Proposition,
    PropositionAnalysis,
    PropositionAnnotation,
    PropositionAuthor,
    PropositionContentVersion,
    PropositionEmbedding,
    PropositionEvent,
    PropositionRapporteur,
)


class _PropositionDeletionCollector(NestedObjects):
    deferred_fields = {
        Proposition: ("ementa", "keywords", "full_text", "raw_payload"),
        PropositionEvent: ("description", "dispatch", "raw_payload"),
        PropositionAnalysis: (
            "theme_scores",
            "favorability_scores",
            "expert_opinion",
            "ai_summary",
            "analysis_error",
        ),
        PropositionContentVersion: ("text",),
        ClassificationRequest: ("input_text", "result"),
        PropositionAnnotation: ("comments",),
        PropositionEmbedding: ("embedding",),
    }

    def related_objects(self, related_model, related_fields, objs):
        queryset = super().related_objects(related_model, related_fields, objs)
        deferred = list(self.deferred_fields.get(related_model, ()))
        for related_field in related_fields:
            deferred.extend(
                f"{related_field.name}__{field}"
                for field in self.deferred_fields.get(related_field.remote_field.model, ())
            )
        return queryset.defer(*deferred)


@admin.register(IgnoredProposition)
class IgnoredPropositionAdmin(ModelAdmin):
    list_display = ["number_label", "house", "external_id", "ignored_at"]
    list_filter = ["house"]
    search_fields = ["number_label", "external_id"]
    readonly_fields = ["ignored_at"]
    ordering = ["-ignored_at"]


class AuthorInline(TabularInline):
    model = PropositionAuthor
    extra = 0
    fields = [
        "parliamentarian",
        "institutional_author",
        "party",
        "state_at_authorship",
        "order_index",
    ]
    autocomplete_fields = ["parliamentarian", "party"]


class RapporteurInline(TabularInline):
    model = PropositionRapporteur
    extra = 0
    fields = ["parliamentarian", "party", "designated_at", "ended_at"]
    autocomplete_fields = ["parliamentarian", "party"]
    readonly_fields = ["is_current"]

    @admin.display(description="Vigente", boolean=True)
    def is_current(self, obj):
        return obj.is_current


class AnalysisInline(TabularInline):
    model = PropositionAnalysis
    extra = 0
    fields = [
        "analysis_status",
        "theme_category",
        "theme_confidence",
        "classification",
        "classification_probability",
        "quiterometer_score",
        "llm_position",
        "ai_summary",
    ]


class AnnotationInline(TabularInline):
    model = PropositionAnnotation
    extra = 0
    # `legacy_theme` fica fora: o tema livre foi substituído pelo select de
    # `category`, e o texto antigo é histórico (visível só no form da anotação).
    fields = ["organization", "is_favorable", "has_caveats", "relevance", "category", "comments"]
    autocomplete_fields = ["organization"]


@admin.register(Proposition)
class PropositionAdmin(ModelAdmin):
    change_list_template = "admin/propositions/proposition/change_list.html"
    list_display = [
        "number_label",
        "year",
        "house",
        "type_code",
        "is_approved",
        "is_active",
        "presented_at",
    ]
    list_editable = ["is_approved"]
    # EmptyFieldListFilter cobre NULL e '' — os dois estados de "sem inteiro
    # teor" (ex.: OCR que não rodou ou falhou).
    list_filter = [
        "house",
        "is_approved",
        "is_active",
        "type_code",
        ("full_text", admin.EmptyFieldListFilter),
    ]
    search_fields = ["number_label", "ementa", "keywords"]
    readonly_fields = ["created_at", "updated_at"]
    inlines = [AuthorInline, RapporteurInline, AnalysisInline, AnnotationInline]
    ordering = ["-presented_at"]

    def get_urls(self):
        return [
            path(
                "add-links/",
                self.admin_site.admin_view(self.add_links),
                name="propositions_proposition_add_links",
            ),
        ] + super().get_urls()

    def add_links(self, request):
        if not self.has_add_permission(request):
            raise PermissionDenied

        form = PropositionLinksForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            runs = enqueue_manual_links(form.cleaned_data["links"])
            count = len(form.cleaned_data["links"])
            run_ids = ", ".join(str(run.pk) for run in runs)
            self.message_user(
                request,
                f"{count} proposição(ões) enfileirada(s) para coleta e avaliação. "
                f"Execução(ões): {run_ids}. Serão aprovadas automaticamente após a coleta.",
                messages.SUCCESS,
            )
            return redirect("admin:propositions_proposition_changelist")

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Adicionar proposições por link",
            "form": form,
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(request, "admin/propositions/proposition/add_links.html", context)

    def get_deleted_objects(self, objs, request):
        if isinstance(objs, QuerySet):
            objs = objs.defer(*_PropositionDeletionCollector.deferred_fields[Proposition])

        try:
            obj = objs[0]
        except IndexError:
            return [], {}, set(), []

        collector = _PropositionDeletionCollector(
            using=router.db_for_write(obj._meta.model), origin=objs
        )
        collector.collect(objs)
        perms_needed = set()

        def format_callback(related_obj):
            model = related_obj.__class__
            opts = related_obj._meta
            label = f"{capfirst(opts.verbose_name)}: {related_obj}"
            if not self.admin_site.is_registered(model):
                return label
            if not self.admin_site.get_model_admin(model).has_delete_permission(
                request, related_obj
            ):
                perms_needed.add(opts.verbose_name)
            try:
                admin_url = reverse(
                    f"{self.admin_site.name}:{opts.app_label}_{opts.model_name}_change",
                    args=(quote(related_obj.pk),),
                )
            except NoReverseMatch:
                return label
            return format_html(
                '{}: <a href="{}">{}</a>',
                capfirst(opts.verbose_name),
                admin_url,
                related_obj,
            )

        to_delete = collector.nested(format_callback)
        protected = [format_callback(related_obj) for related_obj in collector.protected]
        model_count = {
            model._meta.verbose_name_plural: len(model_objs)
            for model, model_objs in collector.model_objs.items()
        }
        return to_delete, model_count, perms_needed, protected


@admin.register(PropositionEvent)
class PropositionEventAdmin(ActivityCacheAdminMixin, ModelAdmin):
    list_display = ["proposition", "event_at", "description"]
    autocomplete_fields = ["proposition"]


@admin.register(PropositionAnalysis)
class PropositionAnalysisAdmin(ModelAdmin):
    list_display = [
        "proposition",
        "analysis_status",
        "theme_category",
        "classification",
        "quiterometer_score",
        "analyzed_at",
    ]
    readonly_fields = ["analyzed_at", "completed_at", "model_id", "model_revision", "input_hash"]


@admin.register(AssessmentOrganization)
class AssessmentOrganizationAdmin(ActivityCacheAdminMixin, ModelAdmin):
    list_display = ["name", "created_at"]
    search_fields = ["name"]


@admin.register(PropositionAnnotation)
class PropositionAnnotationAdmin(ModelAdmin):
    list_display = [
        "proposition",
        "organization",
        "category",
        "is_favorable",
        "has_caveats",
        "relevance",
    ]
    # full_text é da Proposition, não da anotação: filtra as anotações cuja
    # proposição está sem inteiro teor (linhas inúteis para o dataset de treino).
    list_filter = [
        "category",
        "organization",
        "is_favorable",
        "has_caveats",
        "relevance",
        ("proposition__full_text", admin.EmptyFieldListFilter),
    ]
    search_fields = ["legacy_theme", "comments"]
    autocomplete_fields = ["proposition", "organization"]
    # `legacy_theme` é o tema livre da planilha: consultável, nunca editável.
    readonly_fields = ["legacy_theme", "created_at", "updated_at"]
