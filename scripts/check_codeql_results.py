"""Fail CI on high/critical CodeQL security findings or error-level results."""

import json
import sys
from pathlib import Path


def main(directory: str) -> int:
    reports = list(Path(directory).glob("*.sarif"))
    if not reports:
        print("No CodeQL SARIF reports found", file=sys.stderr)
        return 1
    findings = 0
    for report in reports:
        for run in json.loads(report.read_text())["runs"]:
            rules = {rule["id"]: rule for rule in run["tool"]["driver"].get("rules", [])}
            for result in run.get("results", []):
                rule = rules.get(result.get("ruleId"), {})
                severity = float(rule.get("properties", {}).get("security-severity", 0))
                level = result.get("level", rule.get("defaultConfiguration", {}).get("level"))
                if severity >= 7 or level == "error":
                    findings += 1
                    print(f"Blocking CodeQL finding: {result.get('ruleId', 'unknown')}")
    print(f"CodeQL blocking findings: {findings}")
    return int(findings > 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
