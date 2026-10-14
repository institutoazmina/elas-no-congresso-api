"""Publicação das imagens no bucket do site.

Sem invalidação no CloudFront: a imagem nova aparece quando o cache da
borda expira (``max-age``).
"""

import boto3
from django.conf import settings

CACHE_CONTROL = "public, max-age=3600, must-revalidate"


def _client():
    return boto3.client(
        "s3",
        region_name=settings.AWS_DEFAULT_REGION,
        endpoint_url=settings.OG_AWS_ENDPOINT_URL or None,
    )


def upload(key: str, body: bytes) -> None:
    _client().put_object(
        Bucket=settings.OG_S3_BUCKET,
        Key=key,
        Body=body,
        ContentType="image/png",
        CacheControl=CACHE_CONTROL,
    )


def delete(key: str) -> None:
    _client().delete_object(Bucket=settings.OG_S3_BUCKET, Key=key)
