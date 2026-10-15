"""Publica as imagens originais do CMS (``apps/cms/defaults/``) no bucket do site.

Roda a cada deploy e só envia o que ainda não existe no bucket, para não
sobrescrever uma imagem que a equipe substituiu no admin. ``--force`` regrava
a partir dos originais, desfazendo substituições.
"""

from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand

from apps.cms.images import normalize
from apps.cms.models import HeroPage

DEFAULTS_DIR = Path(__file__).resolve().parents[2] / "defaults"


class Command(BaseCommand):
    help = "Publica no bucket as imagens originais do CMS que ainda não existem."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Regrava mesmo se já existir, desfazendo substituições feitas no admin.",
        )

    def handle(self, *args, force=False, **options):
        for model in HeroPage.__subclasses__():
            field = model._meta.get_field("hero_image")
            name = field.default
            filename = model.DEFAULT_HERO_IMAGE
            if not force and field.storage.exists(name):
                self.stdout.write(f"{name}: já publicado")
                continue
            source = DEFAULTS_DIR / filename
            image = normalize(
                SimpleUploadedFile(filename, source.read_bytes()),
                model.HERO_IMAGE,
                stem=Path(name).stem,
            )
            field.storage.save(name, image)
            self.stdout.write(self.style.SUCCESS(f"{name}: publicado"))
