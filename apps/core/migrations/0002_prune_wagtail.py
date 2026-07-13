from django.db import migrations

# Wagtail (e o app `cms` que o estendia, mais django-taggit, arrastado como
# dependência) foi removido do projeto. As tabelas, porém, continuam órfãs no
# banco — o Django não gera mais migração de remoção para apps que saíram do
# INSTALLED_APPS. Esta migração dropa esses resíduos e limpa os metadados do
# Django (django_migrations / django_content_type).
#
# Ordem importa por causa das FKs para django_content_type (todas NO ACTION,
# pois o Django trata a cascata na aplicação, não no banco):
#   1. DROP das tabelas Wagtail com CASCADE — some com as FKs internas ao
#      Wagtail e com qualquer FK das tabelas de domínio (não há nenhuma).
#   2. Limpa django_admin_log e auth_permission que ainda apontam para os
#      content types do Wagtail, senão o DELETE em django_content_type viola FK.
#   3. Remove os content types, migrações e (implicitamente) permissões órfãs.

WAGTAIL_TABLES = [
    "cms_homepage",
    "taggit_taggeditem",
    "taggit_tag",
    "wagtailadmin_admin",
    "wagtailadmin_editingsession",
    "wagtailcore_collectionviewrestriction_groups",
    "wagtailcore_collectionviewrestriction",
    "wagtailcore_collection",
    "wagtailcore_comment",
    "wagtailcore_commentreply",
    "wagtailcore_groupapprovaltask_groups",
    "wagtailcore_groupapprovaltask",
    "wagtailcore_groupcollectionpermission",
    "wagtailcore_grouppagepermission",
    "wagtailcore_groupsitepermission",
    "wagtailcore_locale",
    "wagtailcore_modellogentry",
    "wagtailcore_pagelogentry",
    "wagtailcore_pagesubscription",
    "wagtailcore_pageviewrestriction_groups",
    "wagtailcore_pageviewrestriction",
    "wagtailcore_page",
    "wagtailcore_referenceindex",
    "wagtailcore_revision",
    "wagtailcore_site",
    "wagtailcore_taskstate",
    "wagtailcore_task",
    "wagtailcore_uploadedfile",
    "wagtailcore_workflowcontenttype",
    "wagtailcore_workflowpage",
    "wagtailcore_workflowstate",
    "wagtailcore_workflowtask",
    "wagtailcore_workflow",
    "wagtaildocs_document",
    "wagtailembeds_embed",
    "wagtailforms_formsubmission",
    "wagtailimages_rendition",
    "wagtailimages_image",
    "wagtailredirects_redirect",
    "wagtailsearch_indexentry",
    "wagtailusers_userprofile",
]

WAGTAIL_APP_LABELS = [
    "cms",
    "taggit",
    "wagtailadmin",
    "wagtailcore",
    "wagtaildocs",
    "wagtailembeds",
    "wagtailforms",
    "wagtailimages",
    "wagtailredirects",
    "wagtailsearch",
    "wagtailsnippets",
    "wagtailusers",
]

_tables_sql = ", ".join(f"public.{t}" for t in WAGTAIL_TABLES)
_labels_sql = ", ".join(f"'{label}'" for label in WAGTAIL_APP_LABELS)

PRUNE_SQL = f"""
DROP TABLE IF EXISTS {_tables_sql} CASCADE;

DELETE FROM django_admin_log
 WHERE content_type_id IN (
     SELECT id FROM django_content_type WHERE app_label IN ({_labels_sql})
 );
DELETE FROM auth_group_permissions
 WHERE permission_id IN (
     SELECT p.id FROM auth_permission p
     JOIN django_content_type ct ON ct.id = p.content_type_id
     WHERE ct.app_label IN ({_labels_sql})
 );
DELETE FROM auth_user_user_permissions
 WHERE permission_id IN (
     SELECT p.id FROM auth_permission p
     JOIN django_content_type ct ON ct.id = p.content_type_id
     WHERE ct.app_label IN ({_labels_sql})
 );
DELETE FROM auth_permission
 WHERE content_type_id IN (
     SELECT id FROM django_content_type WHERE app_label IN ({_labels_sql})
 );
DELETE FROM django_content_type WHERE app_label IN ({_labels_sql});
DELETE FROM django_migrations WHERE app IN ({_labels_sql});
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_extensions"),
    ]

    operations = [
        # Irreversível: sem o pacote Wagtail instalado não há como recriar o
        # schema. reverse_sql = noop mantém `migrate <app> zero` funcional.
        migrations.RunSQL(sql=PRUNE_SQL, reverse_sql=migrations.RunSQL.noop),
    ]
