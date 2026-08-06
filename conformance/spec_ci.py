#!/usr/bin/env python3

import argparse
import datetime
import json
import pathlib
import platform
import subprocess
import sys
import time


ROOT = pathlib.Path(__file__).resolve().parents[1]
CASES = (
    ("SPEC-001", [sys.executable, "tools/vector_tool.py"]),
    ("SPEC-002", [sys.executable, "tools/conformance_tool.py", "--self-test"]),
    ("SPEC-003", [sys.executable, "-m", "unittest", "discover", "-s", "conformance", "-p", "test_*.py", "-v"]),
    ("SPEC-004", [sys.executable, "conformance/report_tool.py", "--self-test"]),
)


def run(case_id, command, output_dir, timeout):
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        status = "pass" if result.returncode == 0 else "fail"
        error_code = None if result.returncode == 0 else f"exit-{result.returncode}"
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired as error:
        status = "fail"
        error_code = "timeout"
        output = (error.stdout or "") + (error.stderr or "")
    log = output_dir / "logs" / f"{case_id.lower()}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(output, encoding="utf-8")
    return {
        "sdk": "spec",
        "platform": {"win32": "windows", "darwin": "macos"}.get(sys.platform, sys.platform),
        "stage": "conformance",
        "case": case_id,
        "status": status,
        "error_code": error_code,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "log": str(log.relative_to(output_dir)),
    }


def main():
    parser = argparse.ArgumentParser(description="Validate the pinned Yuumi specification checkout.")
    parser.add_argument("--spec-sha", required=True)
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    started_wall = datetime.datetime.now(datetime.timezone.utc)
    started = time.monotonic()
    actual = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    expected = [
        {"sdk": "spec", "platform": {"win32": "windows", "darwin": "macos"}.get(sys.platform, sys.platform), "stage": "conformance", "case": case_id}
        for case_id, command in CASES
    ]
    if len(args.spec_sha) != 40 or actual != args.spec_sha:
        results = [
            {**row, "status": "not-run", "error_code": "spec-sha-mismatch", "duration_ms": 0, "log": ""}
            for row in expected
        ]
        configuration_error = f"spec SHA mismatch: expected {args.spec_sha}, checkout is {actual}"
    else:
        results = [run(case_id, command, output_dir, args.timeout) for case_id, command in CASES]
        configuration_error = None
    summary = {
        status: sum(row["status"] == status for row in results)
        for status in ("pass", "fail", "skip", "not-run")
    }
    summary["total"] = len(results)
    complete = summary["pass"] == summary["total"]
    report = {
        "schema_version": 1,
        "started_at": started_wall.isoformat().replace("+00:00", "Z"),
        "duration_ms": int((time.monotonic() - started) * 1000),
        "platform": expected[0]["platform"],
        "architecture": platform.machine() or "unknown",
        "spec_sha": args.spec_sha,
        "repositories": {"spec": actual},
        "toolchains": {"python": platform.python_version()},
        "expected_checks": expected,
        "results": results,
        "cleanup": {"status": "pass", "diagnostics": ["no child process remained after synchronous validation"]},
        "summary": summary,
        "complete": complete,
    }
    if configuration_error:
        report["configuration_error"] = configuration_error
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Yuumi spec validation: pass={summary['pass']} fail={summary['fail']} not-run={summary['not-run']} complete={complete}")
    if configuration_error:
        return 2
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())


"""
This entrypoint gives the preliminary specification job the same report shape
as an SDK cell and writes the report even for a SHA mismatch.
"""
