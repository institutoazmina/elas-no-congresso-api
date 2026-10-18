"""Explicitly record reviewed inference outputs; never called by the test suite."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from dataclasses import asdict
from pathlib import Path


def token_fingerprint(tokenizer, text, max_length):
    ids = tokenizer.encode(text, truncation=True, max_length=max_length)
    return {"length": len(ids), "sha256": hashlib.sha256(json.dumps(ids).encode()).hexdigest()}


def artifact_fingerprint(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.output.exists() and not args.overwrite:
        parser.error("Baseline exists; review changes and explicitly pass --overwrite")

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
    import django

    django.setup()
    import torch
    from django.conf import settings

    from apps.propositions.quiteria import MAX_LENGTH, QuiteriaClassifier

    torch.set_num_threads(1)
    classifier = QuiteriaClassifier(str(args.model_dir))
    corpus = Path(__file__).parents[1] / "tests/fixtures/compatibility/quiteria-inputs.json"
    cases = []
    for item in json.loads(corpus.read_text()):
        text = item["text"] + item.get("repeat", "") * item.get("repeat_count", 0)
        cases.append(
            {
                "id": item["id"],
                "prediction": asdict(classifier.classify(text)),
                "tokenization": {
                    "theme": token_fingerprint(classifier._theme_tokenizer, text, MAX_LENGTH),
                    "favorability": token_fingerprint(
                        classifier._favorability_tokenizer, text, MAX_LENGTH
                    ),
                },
            }
        )
    artifact_hashes = {
        str(path.relative_to(args.model_dir)): artifact_fingerprint(path)
        for folder in ("tema", "favorabilidade")
        for path in sorted((args.model_dir / folder).iterdir())
        if path.is_file()
    }
    baseline = {
        "model_id": settings.QUITERIA_MODEL_ID,
        "model_revision": settings.QUITERIA_MODEL_REVISION,
        "versions": {name: importlib.metadata.version(name) for name in ("torch", "transformers")},
        "max_length": MAX_LENGTH,
        "favorability_threshold": settings.QUITERIA_FAVORABILITY_THRESHOLD,
        "artifact_sha256": artifact_hashes,
        "cases": cases,
    }
    args.output.write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n")
    print(f"Recorded {len(cases)} cases in {args.output}")


if __name__ == "__main__":
    main()
