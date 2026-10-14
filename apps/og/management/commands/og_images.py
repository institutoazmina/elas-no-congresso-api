from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.og.models import ParliamentarianOgImage
from apps.og.services import render_target, sync
from apps.og.targets import build_targets


class Command(BaseCommand):
    help = "Publica as imagens de compartilhamento das parlamentares (carga inicial e depuração)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--mode",
            choices=["diff", "force"],
            default="diff",
            help="diff publica só o que mudou; force renderiza tudo de novo.",
        )
        parser.add_argument(
            "--id", type=int, action="append", dest="ids", help="Parlamentar (repetível)."
        )
        parser.add_argument(
            "--output",
            type=Path,
            help="Grava os PNGs neste diretório em vez de publicar no S3.",
        )

    def handle(self, *args, **options):
        ids = set(options["ids"]) if options["ids"] else None
        force = options["mode"] == "force"
        targets = build_targets(ids)

        if options["output"]:
            options["output"].mkdir(parents=True, exist_ok=True)
            for target in targets.values():
                png, _ = render_target(target)
                path = options["output"] / f"{target.slug}.png"
                path.write_bytes(png)
                self.stdout.write(str(path))
            return

        # Quem tem imagem publicada mas deixou de ser alvo perde a imagem.
        records = ParliamentarianOgImage.objects.all()
        if ids is not None:
            records = records.filter(parliamentarian_id__in=ids)
        published = set(records.values_list("parliamentarian_id", flat=True))
        candidates = {**dict.fromkeys(published - set(targets)), **targets}

        results = Counter()
        for parliamentarian_id, target in candidates.items():
            results[sync(parliamentarian_id, target, force=force)] += 1
        self.stdout.write(self.style.SUCCESS(f"{len(candidates)} parlamentares: {dict(results)}"))
