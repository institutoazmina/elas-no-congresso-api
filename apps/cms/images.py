"""Validação e normalização das imagens enviadas pelo CMS.

O layout do site recorta cada imagem com porcentagens fixas, calculadas para
um tamanho específico. A imagem enviada precisa ter a mesma proporção; ela é
regravada em WebP no tamanho exato, o que também descarta metadados.
"""

import io
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

ACCEPTED_FORMATS = {"PNG", "JPEG", "WEBP"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ASPECT_TOLERANCE = 0.02


@dataclass(frozen=True)
class ImageSpec:
    width: int
    height: int

    @property
    def label(self) -> str:
        return f"{self.width}×{self.height} px"


def normalize(upload, spec: ImageSpec, *, stem: str) -> ContentFile:
    if upload.size > MAX_UPLOAD_BYTES:
        raise ValidationError("A imagem deve ter no máximo 5 MB.")
    upload.seek(0)
    try:
        image: Image.Image = Image.open(upload)
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValidationError("Não foi possível ler a imagem enviada.") from exc
    if image.format not in ACCEPTED_FORMATS:
        raise ValidationError("Envie a imagem em PNG, JPEG ou WebP.")

    image = ImageOps.exif_transpose(image)
    expected = spec.width / spec.height
    if abs(image.width / image.height - expected) / expected > ASPECT_TOLERANCE:
        raise ValidationError(
            f"A imagem deve ter a mesma proporção de {spec.label}; a enviada tem "
            f"{image.width}×{image.height} px."
        )
    if image.width < spec.width or image.height < spec.height:
        raise ValidationError(
            f"A imagem deve ter pelo menos {spec.label}; a enviada tem "
            f"{image.width}×{image.height} px."
        )

    image = ImageOps.fit(image.convert("RGBA"), (spec.width, spec.height), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "WEBP", quality=90)
    return ContentFile(buffer.getvalue(), name=f"{stem}.webp")


def normalize_logo(upload) -> ContentFile:
    """Aceita proporções variadas, limita o tamanho e remove metadados do logo."""
    if upload.size > MAX_UPLOAD_BYTES:
        raise ValidationError("O logo deve ter no máximo 5 MB.")
    upload.seek(0)
    try:
        image: Image.Image = Image.open(upload)
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValidationError("Não foi possível ler o logo enviado.") from exc
    if image.format not in ACCEPTED_FORMATS:
        raise ValidationError("Envie o logo em PNG, JPEG ou WebP.")
    image = ImageOps.exif_transpose(image)
    image.thumbnail((640, 640), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.convert("RGBA").save(buffer, "WEBP", quality=90)
    return ContentFile(buffer.getvalue(), name="logo.webp")
