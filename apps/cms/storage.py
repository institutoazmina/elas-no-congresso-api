"""Imagens do CMS no bucket do site, servidas pelo domínio do site.

Cada campo de imagem tem um arquivo fixo (``cms/<página>/<campo>.webp``): enviar
outra imagem sobrescreve o arquivo e invalida o caminho no CloudFront. O admin
não permite remover a imagem, só substituí-la.
Sem bucket, como em desenvolvimento e testes, delega ao storage padrão
(``MEDIA_ROOT``).
"""

import mimetypes
import uuid

import boto3
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.files.storage import Storage, default_storage
from django.utils.deconstruct import deconstructible

# Igual aos demais assets de URL estável; a API acrescenta ``?v=`` à URL para o
# navegador buscar a versão nova depois do deploy.
CACHE_CONTROL = "public, max-age=3600, must-revalidate"


def _client():
    return boto3.client(
        "s3",
        region_name=settings.AWS_DEFAULT_REGION,
        endpoint_url=settings.OG_AWS_ENDPOINT_URL or None,
    )


def _cloudfront():
    return boto3.client("cloudfront")


def invalidate(name: str) -> None:
    if not settings.CMS_CLOUDFRONT_DISTRIBUTION_ID:
        return
    # O curinga cobre as variantes com query string (``?v=``).
    _cloudfront().create_invalidation(
        DistributionId=settings.CMS_CLOUDFRONT_DISTRIBUTION_ID,
        InvalidationBatch={
            "Paths": {"Quantity": 1, "Items": [f"/{name}*"]},
            "CallerReference": uuid.uuid4().hex,
        },
    )


@deconstructible
class CmsStorage(Storage):
    def get_available_name(self, name, max_length=None):
        # Sobrescreve em vez de criar ``hero_ab12cd.webp`` ao lado.
        return name

    def _save(self, name, content):
        if not settings.CMS_S3_BUCKET:
            if default_storage.exists(name):
                default_storage.delete(name)
            return default_storage.save(name, content)
        content.seek(0)
        _client().put_object(
            Bucket=settings.CMS_S3_BUCKET,
            Key=name,
            Body=content.read(),
            ContentType=mimetypes.guess_type(name)[0] or "application/octet-stream",
            CacheControl=CACHE_CONTROL,
        )
        invalidate(name)
        return name

    def _open(self, name, mode="rb"):
        return default_storage.open(name, mode)

    def exists(self, name):
        if not settings.CMS_S3_BUCKET:
            return default_storage.exists(name)
        try:
            _client().head_object(Bucket=settings.CMS_S3_BUCKET, Key=name)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {"404", "NoSuchKey"}:
                return False
            raise
        return True

    def url(self, name):
        if not settings.CMS_S3_BUCKET:
            return default_storage.url(name)
        return f"{settings.CMS_PUBLIC_BASE_URL.rstrip('/')}/{name}"
