#!/usr/bin/env python3

import argparse
import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parent
SCHEMA_PATH = ROOT / "report.schema.json"
STATUSES = {"pass", "fail", "skip", "not-run"}
REQUIRED = {
    "schema_version",
    "started_at",
    "duration_ms",
    "platform",
    "architecture",
    "spec_sha",
    "repositories",
    "toolchains",
    "expected_checks",
    "results",
    "cleanup",
    "summary",
    "complete",
}


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON {path}: {error}") from error


def row_key(row):
    return tuple(row.get(key) for key in ("sdk", "platform", "stage", "case"))


def validate(report):
    errors = []
    missing = REQUIRED - set(report) if isinstance(report, dict) else REQUIRED
    if missing:
        return [f"missing report fields: {sorted(missing)}"]
    if report["schema_version"] != 1:
        errors.append("schema_version must be 1")
    if report["platform"] not in {"windows", "linux", "macos"}:
        errors.append("platform is invalid")
    spec_sha = report["spec_sha"]
    if not isinstance(spec_sha, str) or len(spec_sha) != 40 or any(
        character not in "0123456789abcdef" for character in spec_sha
    ):
        errors.append("spec_sha must be a full lowercase commit SHA")
    expected_rows = report["expected_checks"]
    result_rows = report["results"]
    if not isinstance(expected_rows, list) or not isinstance(result_rows, list):
        return errors + ["expected_checks and results must be arrays"]
    expected = [row_key(row) for row in expected_rows]
    observed = [row_key(row) for row in result_rows]
    if len(expected) != len(set(expected)):
        errors.append("expected_checks contains duplicate checks")
    if len(observed) != len(set(observed)):
        errors.append("results contain duplicate cells")
    if set(expected) != set(observed):
        errors.append("results do not exactly match expected_checks")
    for row in result_rows:
        if row.get("status") not in STATUSES:
            errors.append(f"invalid status for {row_key(row)}: {row.get('status')}")
    calculated = {
        status: sum(row.get("status") == status for row in result_rows)
        for status in STATUSES
    }
    calculated["total"] = len(result_rows)
    if report["summary"] != calculated:
        errors.append("summary does not match result rows")
    cleanup_ok = report.get("cleanup", {}).get("status") == "pass"
    calculated_complete = (
        calculated["total"] == len(expected_rows)
        and calculated["pass"] == calculated["total"]
        and cleanup_ok
    )
    if report["complete"] != calculated_complete:
        errors.append("complete does not match results and cleanup")
    if report["complete"] and any(calculated[status] for status in ("fail", "skip", "not-run")):
        errors.append("complete report contains a non-pass result")
    return errors


def self_test():
    row = {"sdk": "go", "platform": "linux", "stage": "conformance", "case": "CC-001"}
    report = {
        "schema_version": 1,
        "started_at": "2026-01-01T00:00:00Z",
        "duration_ms": 1,
        "platform": "linux",
        "architecture": "x86_64",
        "spec_sha": "0" * 40,
        "repositories": {},
        "toolchains": {},
        "expected_checks": [row],
        "results": [{**row, "status": "pass", "error_code": None, "duration_ms": 1, "log": "case.log"}],
        "cleanup": {"status": "pass", "diagnostics": []},
        "summary": {"pass": 1, "fail": 0, "skip": 0, "not-run": 0, "total": 1},
        "complete": True,
    }
    if validate(report):
        return ["valid report was rejected"]
    incomplete = {
        **report,
        "results": [],
        "summary": {"pass": 0, "fail": 0, "skip": 0, "not-run": 0, "total": 0},
        "complete": False,
    }
    errors = validate(incomplete)
    if not any("expected_checks" in error for error in errors):
        return ["missing mandatory check was not rejected"]
    report["results"][0]["status"] = "skip"
    report["summary"] = {"pass": 0, "fail": 0, "skip": 1, "not-run": 0, "total": 1}
    report["complete"] = False
    if validate(report):
        return ["internally consistent skip report was rejected"]
    report["complete"] = True
    errors = validate(report)
    if not any("complete" in error for error in errors):
        return ["mandatory skip did not invalidate complete"]
    return []


def main():
    parser = argparse.ArgumentParser(description="Validate a Yuumi conformance report.")
    parser.add_argument("report", type=pathlib.Path, nargs="?")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        schema = load(SCHEMA_PATH)
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise ValueError("report schema does not declare JSON Schema 2020-12")
        errors = self_test() if args.self_test else validate(load(args.report))
    except (TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("PASS: report schema and mandatory-completeness gate are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


"""
The validator intentionally has no third-party dependency. It validates the
closed report contract needed by CI, including exact check coverage and the
rule that skip, not-run, failure, or cleanup failure makes complete false.
"""
