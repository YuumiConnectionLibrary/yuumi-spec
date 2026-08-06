#!/usr/bin/env python3

import argparse
import datetime
import json
import os
import pathlib
import platform
import re
import signal
import subprocess
import sys
import time


SPEC_ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST_PATH = SPEC_ROOT / "conformance" / "manifest.json"
INTEROP_MANIFEST_PATH = SPEC_ROOT / "conformance" / "interop_manifest.json"
REPOSITORIES = {
    "spec": "yuumi-spec",
    "go": "Yuumi",
    "cpp": "yuumi-cpp",
    "python": "yuumi-py",
    "rust": "yuumi-rs",
    "typescript": "yuumi-ts",
}
ENGINES = ("cpp", "python", "rust", "typescript")
PLATFORMS = {"windows", "linux", "macos"}
SHA_RE = re.compile(r"[0-9a-f]{40}")
CASE_RE = re.compile(r"([CE]C)[_-]?(\d{3})(?!\d)", re.IGNORECASE)
INTEROP_RE = re.compile(
    r"---\s+(PASS|FAIL|SKIP):\s+TestGoEngineInterop/([A-Za-z0-9_]+)",
    re.IGNORECASE,
)


class ConfigurationError(Exception):
    pass


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigurationError(f"cannot read {path}: {error}") from error


def git_output(repository, *arguments):
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def normalize_platform(value):
    aliases = {"win32": "windows", "darwin": "macos"}
    normalized = aliases.get(value.lower(), value.lower())
    if normalized not in PLATFORMS:
        raise ConfigurationError(f"unsupported expected platform: {value}")
    return normalized


def actual_platform():
    return normalize_platform(sys.platform)


def version(command, cwd):
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (result.stdout or result.stderr).strip().splitlines()
    return output[0] if output else None


def terminate_owned(process):
    diagnostics = []
    if process.poll() is not None:
        return True, [f"pid {process.pid} already exited"]
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            diagnostics.append(f"taskkill pid {process.pid} exit={result.returncode}")
        else:
            os.killpg(process.pid, signal.SIGTERM)
            diagnostics.append(f"SIGTERM process group {process.pid}")
        process.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired) as error:
        diagnostics.append(f"cleanup failed for pid {process.pid}: {error}")
        return False, diagnostics
    return process.poll() is not None, diagnostics


def run_command(command, cwd, environment, timeout, log_path):
    started = time.monotonic()
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=os.name != "nt",
        creationflags=creationflags,
    )
    timed_out = False
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        cleanup_ok, diagnostics = terminate_owned(process)
        if not cleanup_ok and process.poll() is None:
            process.kill()
        output, _ = process.communicate(timeout=10)
        output += "\nHARNESS TIMEOUT\n" + "\n".join(diagnostics)
        if not cleanup_ok:
            output += "\nHARNESS CLEANUP FAILURE\n"
    duration_ms = int((time.monotonic() - started) * 1000)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(output, encoding="utf-8")
    return process.returncode, output, duration_ms, timed_out


def finalize_report(report):
    for status in ("pass", "fail", "skip", "not-run"):
        report["summary"][status] = sum(
            row["status"] == status for row in report["results"]
        )
    report["summary"]["total"] = len(report["results"])
    report["complete"] = (
        report["summary"]["total"] == len(report["expected_checks"])
        and report["summary"]["pass"] == report["summary"]["total"]
        and report["cleanup"]["status"] == "pass"
    )


def report_exit_code(report):
    if report["cleanup"]["status"] != "pass" or report["summary"]["fail"]:
        return 1
    if report["summary"]["skip"] or report["summary"]["not-run"] or not report["complete"]:
        return 3
    return 0


def merge_status(current, incoming):
    precedence = {"not-run": 0, "pass": 1, "skip": 2, "fail": 3}
    return incoming if precedence[incoming] >= precedence[current] else current


def parse_go_conformance(output):
    statuses = {}
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        action = event.get("Action")
        test = event.get("Test", "")
        if action not in {"pass", "fail", "skip"}:
            continue
        for prefix, digits in CASE_RE.findall(test):
            case_id = f"{prefix.upper()}-{digits}"
            statuses[case_id] = merge_status(statuses.get(case_id, "not-run"), action)
    return statuses


def parse_text_conformance(output):
    statuses = {}
    for line in output.splitlines():
        matches = CASE_RE.findall(line)
        if not matches:
            continue
        lowered = line.lower()
        stripped = lowered.strip()
        if " skipped" in lowered or " ignored" in lowered or "not run" in lowered or "# skip" in lowered:
            status = "skip"
        elif (
            stripped.startswith("not ok")
            or "***failed" in lowered
            or re.search(r"\.\.\.\s+(fail|failed|error)\b", lowered)
        ):
            status = "fail"
        elif (
            stripped.startswith("ok ")
            or re.search(r"\.\.\.\s+ok\b", lowered)
            or re.search(r"\bpassed\b", lowered)
        ):
            status = "pass"
        else:
            continue
        for prefix, digits in matches:
            case_id = f"{prefix.upper()}-{digits}"
            statuses[case_id] = merge_status(statuses.get(case_id, "not-run"), status)
    return statuses


def parse_interop(output, manifest):
    by_test = {item["test"]: item["id"] for item in manifest["cases"]}
    statuses = {}
    for status, test_name in INTEROP_RE.findall(output):
        case_id = by_test.get(test_name)
        if case_id is None:
            continue
        statuses[case_id] = merge_status(
            statuses.get(case_id, "not-run"), status.lower()
        )
    return statuses


def suite_commands(root, sdk, stage, cpp_build_dir, cpp_configuration):
    repositories = {key: root / value for key, value in REPOSITORIES.items()}
    ctest_configuration = ["-C", cpp_configuration] if actual_platform() == "windows" else []
    if stage == "conformance":
        commands = {
            "go": (["go", "test", "-json", "./...", "-count=1", "-timeout", "120s"], repositories["go"], "go"),
            "cpp": (["ctest", "--test-dir", str(cpp_build_dir), *ctest_configuration, "--output-on-failure", "-V", "-R", "yuumi_EC-"], repositories["cpp"], "text"),
            "python": ([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"], repositories["python"], "text"),
            "rust": (["cargo", "test", "--locked", "--test", "engine_conformance", "--", "--nocapture"], repositories["rust"], "text"),
            "typescript": (["node", "--test", "--test-reporter=tap", "tests/engine_conformance.test.js"], repositories["typescript"], "text"),
        }
        return commands[sdk]
    commands = {
        "cpp": (["ctest", "--test-dir", str(cpp_build_dir), *ctest_configuration, "--output-on-failure", "-V", "-R", "^yuumi_go_integration$"], repositories["cpp"], "interop"),
        "python": ([sys.executable, "integration/run.py"], repositories["python"], "interop"),
        "rust": (["cargo", "run", "--locked", "--example", "yuumi_go_integration_adapter"], repositories["rust"], "interop"),
        "typescript": (["node", "--test", "--test-reporter=tap", "tests/go_integration.test.js"], repositories["typescript"], "interop"),
    }
    return commands[sdk]


def expected_cases(manifest, interop_manifest, sdk, stages, expected_platform):
    rows = []
    if "conformance" in stages:
        contract = "client" if sdk == "go" else "engine"
        for case in manifest["cases"]:
            if case["contract"] == contract:
                rows.append({"sdk": sdk, "platform": expected_platform, "stage": "conformance", "case": case["id"]})
    if "interop" in stages and sdk in ENGINES:
        for case in interop_manifest["cases"]:
            rows.append({"sdk": sdk, "platform": expected_platform, "stage": "interop", "case": case["id"]})
    return rows


def validate_configuration(args, root):
    if SHA_RE.fullmatch(args.spec_sha) is None:
        raise ConfigurationError("spec SHA must be a full lowercase 40-character commit SHA")
    expected_platform = normalize_platform(args.platform)
    if actual_platform() != expected_platform:
        raise ConfigurationError(
            f"expected platform {expected_platform}, running on {actual_platform()}"
        )
    spec_repository = root / REPOSITORIES["spec"]
    if spec_repository.resolve() != SPEC_ROOT.resolve():
        raise ConfigurationError(
            f"harness spec checkout {SPEC_ROOT} does not match {spec_repository}"
        )
    actual_sha = git_output(spec_repository, "rev-parse", "HEAD")
    if actual_sha != args.spec_sha:
        raise ConfigurationError(
            f"spec SHA mismatch: expected {args.spec_sha}, checkout is {actual_sha}"
        )
    sdk = args.sdk
    if sdk not in REPOSITORIES or sdk == "spec":
        raise ConfigurationError(f"unsupported SDK: {sdk}")
    stages = {args.stage} if args.stage != "all" else {"conformance", "interop"}
    if "interop" in stages and sdk not in ENGINES:
        stages.remove("interop")
    repository = root / REPOSITORIES[sdk]
    if not (repository / ".git").exists():
        raise ConfigurationError(f"missing repository checkout: {repository}")
    if sdk in ENGINES and "interop" in stages:
        go_repository = root / REPOSITORIES["go"]
        if not (go_repository / "go.mod").is_file():
            raise ConfigurationError(f"missing Go checkout for interop: {go_repository}")
    return expected_platform, sdk, stages


def collect_revisions(root):
    return {
        name: git_output(root / directory, "rev-parse", "HEAD")
        if (root / directory / ".git").exists()
        else None
        for name, directory in REPOSITORIES.items()
    }


def collect_toolchains(root):
    return {
        "python": version([sys.executable, "--version"], root),
        "go": version(["go", "version"], root),
        "cmake": version(["cmake", "--version"], root),
        "cxx": version([os.environ.get("CXX", "c++"), "--version"], root),
        "rust": version(["rustc", "--version"], root),
        "cargo": version(["cargo", "--version"], root),
        "node": version(["node", "--version"], root),
        "npm": version(["npm", "--version"], root),
    }


def write_report(report, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report_path


def main():
    parser = argparse.ArgumentParser(description="Run one Yuumi SDK conformance cell.")
    parser.add_argument("--repositories-root", type=pathlib.Path, required=True)
    parser.add_argument("--spec-sha", required=True)
    parser.add_argument("--platform", choices=tuple(sorted(PLATFORMS)), required=True)
    parser.add_argument("--sdk", choices=tuple(REPOSITORIES)[1:], required=True)
    parser.add_argument("--stage", choices=("all", "conformance", "interop"), default="all")
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--cpp-build-dir", type=pathlib.Path)
    parser.add_argument("--cpp-configuration", default="Debug")
    parser.add_argument("--fault", choices=("case-fail", "case-skip", "cleanup-fail", "report-corrupt"))
    args = parser.parse_args()
    started_wall = datetime.datetime.now(datetime.timezone.utc)
    started = time.monotonic()
    output_dir = args.output_dir.resolve()
    report = {
        "schema_version": 1,
        "started_at": started_wall.isoformat().replace("+00:00", "Z"),
        "duration_ms": 0,
        "platform": normalize_platform(args.platform),
        "architecture": platform.machine() or "unknown",
        "spec_sha": args.spec_sha,
        "repositories": {},
        "toolchains": {},
        "expected_checks": [],
        "results": [],
        "cleanup": {"status": "pass", "diagnostics": []},
        "summary": {"pass": 0, "fail": 0, "skip": 0, "not-run": 0, "total": 0},
        "complete": False,
    }
    try:
        root = args.repositories_root.resolve()
        expected_platform, sdk, stages = validate_configuration(args, root)
        manifest = load_json(MANIFEST_PATH)
        interop_manifest = load_json(INTEROP_MANIFEST_PATH)
        report["repositories"] = collect_revisions(root)
        report["toolchains"] = collect_toolchains(root)
        report["expected_checks"] = expected_cases(
            manifest, interop_manifest, sdk, stages, expected_platform
        )
        cpp_build_dir = (args.cpp_build_dir or root / REPOSITORIES["cpp"] / "build" / "ci").resolve()
        for stage in ("conformance", "interop"):
            if stage not in stages or (stage == "interop" and sdk not in ENGINES):
                continue
            command, cwd, parser_kind = suite_commands(
                root, sdk, stage, cpp_build_dir, args.cpp_configuration
            )
            log_path = output_dir / "logs" / f"{sdk}-{stage}.log"
            environment = os.environ.copy()
            environment["YUUMI_SPEC_SHA"] = args.spec_sha
            code, output, duration, timed_out = run_command(
                command, cwd, environment, args.timeout, log_path
            )
            report["cleanup"]["diagnostics"].append(
                f"{sdk}/{stage}: owned process exited with code {code}"
            )
            if "HARNESS CLEANUP FAILURE" in output:
                report["cleanup"]["status"] = "fail"
            if parser_kind == "go":
                statuses = parse_go_conformance(output)
            elif parser_kind == "interop":
                statuses = parse_interop(output, interop_manifest)
            else:
                statuses = parse_text_conformance(output)
            expected = [
                row for row in report["expected_checks"] if row["stage"] == stage
            ]
            for row in expected:
                status = statuses.get(row["case"], "not-run")
                error_code = None
                if timed_out:
                    status, error_code = "fail", "timeout"
                elif code != 0 and status == "not-run":
                    error_code = "suite-failed-before-case"
                report["results"].append({
                    **row,
                    "status": status,
                    "error_code": error_code,
                    "duration_ms": duration,
                    "log": str(log_path.relative_to(output_dir)),
                })
        if args.fault and report["results"]:
            if args.fault == "case-fail":
                report["results"][0]["status"] = "fail"
                report["results"][0]["error_code"] = "injected"
            elif args.fault == "case-skip":
                report["results"][0]["status"] = "skip"
                report["results"][0]["error_code"] = "injected"
            elif args.fault == "cleanup-fail":
                report["cleanup"] = {"status": "fail", "diagnostics": ["injected cleanup failure"]}
        observed = {(row["sdk"], row["platform"], row["stage"], row["case"]) for row in report["results"]}
        expected = {(row["sdk"], row["platform"], row["stage"], row["case"]) for row in report["expected_checks"]}
        for missing in sorted(expected - observed):
            sdk, platform_name, stage, case_id = missing
            report["results"].append({
                "sdk": sdk,
                "platform": platform_name,
                "stage": stage,
                "case": case_id,
                "status": "not-run",
                "error_code": "missing-result",
                "duration_ms": 0,
                "log": "",
            })
    except (ConfigurationError, OSError) as error:
        report["configuration_error"] = str(error)
        report["cleanup"]["diagnostics"].append("configuration rejected before suite execution")
        report["duration_ms"] = int((time.monotonic() - started) * 1000)
        write_report(report, output_dir)
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    finalize_report(report)
    report["duration_ms"] = int((time.monotonic() - started) * 1000)
    report_path = write_report(report, output_dir)
    if args.fault == "report-corrupt":
        report_path.write_text("{", encoding="utf-8")
        print("ERROR: injected corrupt report", file=sys.stderr)
        return 3
    print(
        f"Yuumi conformance: pass={report['summary']['pass']} "
        f"fail={report['summary']['fail']} skip={report['summary']['skip']} "
        f"not-run={report['summary']['not-run']} complete={report['complete']}"
    )
    return report_exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())


"""
The harness owns only subprocesses it starts and records every expected check
before execution. Missing output therefore becomes not-run instead of a false
success. Workflow setup installs dependencies; the harness never downloads or
checks out repositories, and it never orchestrates more than one SDK.
"""
