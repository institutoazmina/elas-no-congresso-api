import json

import pytest

from scripts.check_codeql_results import main


@pytest.mark.parametrize(
    ("severity", "level", "expected"),
    [("9.8", "warning", 1), ("7.0", "warning", 1), ("6.9", "warning", 0), ("0", "error", 1)],
)
def test_codeql_gate_thresholds(tmp_path, severity, level, expected):
    report = {
        "runs": [
            {
                "tool": {
                    "driver": {
                        "rules": [
                            {
                                "id": "py/test-rule",
                                "properties": {"security-severity": severity},
                                "defaultConfiguration": {"level": level},
                            }
                        ]
                    }
                },
                "results": [{"ruleId": "py/test-rule"}],
            }
        ]
    }
    (tmp_path / "python.sarif").write_text(json.dumps(report))
    assert main(str(tmp_path)) == expected


def test_codeql_gate_requires_report(tmp_path):
    assert main(str(tmp_path)) == 1


def test_codeql_gate_accepts_clean_report(tmp_path):
    report = {"runs": [{"tool": {"driver": {}}, "results": []}]}
    (tmp_path / "actions.sarif").write_text(json.dumps(report))
    assert main(str(tmp_path)) == 0


def test_codeql_gate_checks_every_report(tmp_path):
    clean = {"runs": [{"tool": {"driver": {}}, "results": []}]}
    error = {"runs": [{"tool": {"driver": {}}, "results": [{"level": "error"}]}]}
    (tmp_path / "actions.sarif").write_text(json.dumps(clean))
    (tmp_path / "python.sarif").write_text(json.dumps(error))
    assert main(str(tmp_path)) == 1
