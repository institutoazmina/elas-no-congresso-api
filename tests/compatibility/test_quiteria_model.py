"""Real CPU inference against fixed weights and pre-upgrade golden outputs."""

import hashlib
import json
import math
import os
from pathlib import Path

import pytest

from apps.propositions.quiteria import MAX_LENGTH, QuiteriaClassifier
from scripts.record_quiteria_baseline import token_fingerprint

FIXTURES = Path(__file__).parents[1] / "fixtures" / "compatibility"
BASELINE = json.loads((FIXTURES / "quiteria-baseline.json").read_text())
CORPUS = {case["id"]: case for case in json.loads((FIXTURES / "quiteria-inputs.json").read_text())}
pytestmark = pytest.mark.ml


@pytest.fixture(scope="module")
def classifier(request):
    if not request.config.getoption("--run-ml"):
        pytest.skip("Use --run-ml and QUITERIA_TEST_MODEL_DIR for real-model compatibility")
    root = Path(os.environ.get("QUITERIA_TEST_MODEL_DIR", "/missing-model"))
    assert root.is_dir(), "QUITERIA_TEST_MODEL_DIR must contain the pinned model artifacts"
    # Reject missing, changed or substituted weights before trusting predictions.
    for name, expected in BASELINE["artifact_sha256"].items():
        with (root / name).open("rb") as source:
            assert hashlib.file_digest(source, "sha256").hexdigest() == expected, name
    import torch

    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        yield QuiteriaClassifier(str(root))
    finally:
        torch.set_num_threads(previous)


def test_model_contract_matches_baseline(classifier, settings):
    assert {case["id"] for case in BASELINE["cases"]} == set(CORPUS)
    assert BASELINE["model_id"] == settings.QUITERIA_MODEL_ID
    assert BASELINE["model_revision"] == settings.QUITERIA_MODEL_REVISION
    assert BASELINE["favorability_threshold"] == settings.QUITERIA_FAVORABILITY_THRESHOLD
    assert BASELINE["max_length"] == MAX_LENGTH
    assert next(classifier._theme_model.parameters()).device.type == "cpu"
    assert next(classifier._favorability_model.parameters()).device.type == "cpu"


@pytest.mark.parametrize("case", BASELINE["cases"], ids=lambda case: case["id"])
def test_real_inference_preserves_tokenization_labels_and_scores(classifier, case):
    expected = case["prediction"]
    source = CORPUS[case["id"]]
    text = source["text"] + source.get("repeat", "") * source.get("repeat_count", 0)
    assert text == expected["input_text"]
    for name, tokenizer in (
        ("theme", classifier._theme_tokenizer),
        ("favorability", classifier._favorability_tokenizer),
    ):
        assert token_fingerprint(tokenizer, text, MAX_LENGTH) == case["tokenization"][name]
    prediction = classifier.classify(text)
    assert prediction.theme_category == expected["theme_category"]
    assert prediction.favorability_label == expected["favorability_label"]
    assert prediction.input_hash == hashlib.sha256(text.encode()).hexdigest()
    for field in ("theme_scores", "favorability_scores"):
        scores = getattr(prediction, field)
        assert all(math.isfinite(value) and 0 <= value <= 1 for value in scores.values())
        assert sum(scores.values()) == pytest.approx(1, abs=1e-5)
        assert scores == pytest.approx(expected[field], abs=1e-4, rel=1e-3)
    assert prediction.theme_confidence == pytest.approx(
        expected["theme_confidence"], abs=1e-4, rel=1e-3
    )
    assert prediction.favorability_probability == pytest.approx(
        expected["favorability_probability"], abs=1e-4, rel=1e-3
    )
    if case["id"] == "long_input":
        assert all(value["length"] == 512 for value in case["tokenization"].values())
