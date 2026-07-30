#!/usr/bin/env python3

import argparse
import fnmatch
import json
import pathlib
import re
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "conformance" / "manifest.json"
SOURCE_PATHS = (ROOT / "PROTOCOL.md", ROOT / "CLIENT_API.md", ROOT / "ENGINE_API.md")
VECTOR_DIR = ROOT / "test-vectors"
REQUIREMENT_RE = re.compile(r"(?:PROTO|CLI|ENG)-[A-Z]+-[0-9]{3}")
CASE_RE = re.compile(r"(?:CC|EC)-[0-9]{3}")
PLATFORMS = {"windows", "linux", "macos"}
CASE_FIELDS = {
    "id",
    "contract",
    "title",
    "requirements",
    "endpoint_under_test",
    "preconditions",
    "input",
    "action",
    "wire_result",
    "api_result",
    "cleanup",
    "platforms",
    "mandatory",
    "failure_evidence",
}


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        try:
            label = path.relative_to(ROOT)
        except ValueError:
            label = path
        raise ValueError(f"cannot read {label}: {error}") from error


def normative_requirements(errors):
    requirements = set()
    for path in SOURCE_PATHS:
        text = path.read_text(encoding="utf-8")
        identifiers = REQUIREMENT_RE.findall(text)
        for identifier in identifiers:
            if identifier in requirements:
                errors.append(f"duplicate normative requirement ID: {identifier}")
            requirements.add(identifier)
        for paragraph in re.split(r"\n\s*\n", text):
            if "**MUST" not in paragraph or "keywords **MUST" in paragraph:
                continue
            if REQUIREMENT_RE.search(paragraph) is None:
                errors.append(
                    f"{path.name}: normative MUST clause lacks a stable requirement ID: "
                    + " ".join(paragraph.split())[:160]
                )
    return requirements


def expand_requirements(patterns, known, case_id, errors):
    expanded = set()
    for pattern in patterns:
        matches = {requirement for requirement in known if fnmatch.fnmatchcase(requirement, pattern)}
        if not matches:
            errors.append(f"{case_id}: requirement reference matches nothing: {pattern}")
        expanded.update(matches)
    return expanded


def validate_case(case, known, seen_ids, errors):
    missing = sorted(CASE_FIELDS - set(case))
    if missing:
        errors.append(f"case missing fields {missing}: {case.get('id', '<unknown>')}")
        return set()

    case_id = case["id"]
    if CASE_RE.fullmatch(case_id) is None:
        errors.append(f"invalid case ID: {case_id}")
    if case_id in seen_ids:
        errors.append(f"duplicate case ID: {case_id}")
    seen_ids.add(case_id)

    expected_contract = "client" if case_id.startswith("CC-") else "engine"
    if case["contract"] != expected_contract:
        errors.append(f"{case_id}: contract must be {expected_contract}")
    expected_endpoint = "go_client_listener" if expected_contract == "client" else "engine_dialer"
    if case["endpoint_under_test"] != expected_endpoint:
        errors.append(f"{case_id}: endpoint_under_test must be {expected_endpoint}")

    if case["mandatory"] is not True:
        errors.append(f"{case_id}: every conformance case is mandatory")
    if set(case["platforms"]) != PLATFORMS:
        errors.append(f"{case_id}: permanent platform omission is forbidden")

    for field in CASE_FIELDS - {"requirements", "input", "platforms", "mandatory"}:
        if not isinstance(case[field], str) or not case[field].strip():
            errors.append(f"{case_id}: {field} must be a non-empty deterministic statement")

    case_input = case["input"]
    if not isinstance(case_input, dict):
        errors.append(f"{case_id}: input must be an object")
    else:
        if case_input.get("payload_schema") != "opaque":
            errors.append(f"{case_id}: payload_schema must be opaque")
        vectors = case_input.get("vectors")
        if not isinstance(vectors, list):
            errors.append(f"{case_id}: input.vectors must be a list")
        else:
            for vector in vectors:
                vector_path = VECTOR_DIR / vector
                if not vector_path.is_file():
                    errors.append(f"{case_id}: cited vector does not exist: {vector}")
                if vector_path.suffix == ".bin" and not vector_path.with_suffix(".json").is_file():
                    errors.append(f"{case_id}: cited binary lacks annotation: {vector}")
        if not isinstance(case_input.get("constructed"), str) or not case_input["constructed"].strip():
            errors.append(f"{case_id}: input.constructed must be a non-empty statement")
        forbidden_keys = {str(key).lower() for key in case_input} & {"cmd", "data", "required_payload_fields"}
        if forbidden_keys:
            errors.append(f"{case_id}: application payload fields are forbidden: {sorted(forbidden_keys)}")

    return expand_requirements(case["requirements"], known, case_id, errors)


def validate_manifest(manifest):
    errors = []
    if manifest.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if manifest.get("platform_policy", {}).get("permanent_skip") != "forbidden":
        errors.append("platform_policy.permanent_skip must be forbidden")
    if set(manifest.get("platform_policy", {}).get("required", [])) != PLATFORMS:
        errors.append("platform_policy.required must contain Windows, Linux, and macOS")

    known = normative_requirements(errors)
    covered = set()
    seen_ids = set()
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append("cases must be a non-empty list")
        cases = []
    for case in cases:
        if not isinstance(case, dict):
            errors.append("every case must be an object")
            continue
        covered.update(validate_case(case, known, seen_ids, errors))

    missing = sorted(known - covered)
    if missing:
        errors.append("normative requirements without a case: " + ", ".join(missing))

    contracts = {case.get("contract") for case in cases if isinstance(case, dict)}
    if contracts != {"client", "engine"}:
        errors.append("manifest must contain distinct client and engine contracts")
    return errors, known, covered


def validate_results(manifest, results):
    errors = []
    cases = {case["id"]: case for case in manifest["cases"]}
    seen = set()
    rows = results.get("results") if isinstance(results, dict) else None
    if not isinstance(rows, list):
        return ["results must be an object containing a results list"]
    for result in rows:
        if not isinstance(result, dict):
            errors.append("every result must be an object")
            continue
        case_id = result.get("id")
        status = result.get("status")
        if case_id not in cases:
            errors.append(f"result references unknown case: {case_id}")
            continue
        if case_id in seen:
            errors.append(f"duplicate result: {case_id}")
        seen.add(case_id)
        if cases[case_id]["mandatory"] and status == "skip":
            errors.append(f"mandatory case skipped: {case_id}")
        if status not in {"pass", "fail", "skip"}:
            errors.append(f"invalid result status for {case_id}: {status}")
    missing = sorted(set(cases) - seen)
    if missing:
        errors.append("missing mandatory results: " + ", ".join(missing))
    return errors


def self_test_skip_guard(manifest):
    synthetic = {"results": [{"id": case["id"], "status": "pass"} for case in manifest["cases"]]}
    synthetic["results"][0]["status"] = "skip"
    errors = validate_results(manifest, synthetic)
    if not any(error.startswith("mandatory case skipped:") for error in errors):
        return ["skip guard self-test did not reject a mandatory skip"]
    return []


def print_coverage(manifest, known):
    mapping = {requirement: [] for requirement in sorted(known)}
    ignored_errors = []
    for case in manifest["cases"]:
        for requirement in expand_requirements(case["requirements"], known, case["id"], ignored_errors):
            mapping[requirement].append(case["id"])
    for requirement, cases in mapping.items():
        print(f"{requirement}\t{','.join(cases)}")


def main():
    parser = argparse.ArgumentParser(description="Validate Yuumi conformance contracts.")
    parser.add_argument("--coverage", action="store_true", help="print exact requirement-to-case mapping")
    parser.add_argument("--results", type=pathlib.Path, help="validate harness results and reject mandatory skips")
    parser.add_argument("--self-test", action="store_true", help="exercise the mandatory-skip guard")
    args = parser.parse_args()

    try:
        manifest = load_json(MANIFEST_PATH)
        errors, known, covered = validate_manifest(manifest)
        if args.results:
            errors.extend(validate_results(manifest, load_json(args.results.resolve())))
        if args.self_test:
            errors.extend(self_test_skip_guard(manifest))
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if args.coverage:
        print_coverage(manifest, known)
    client_count = sum(case["contract"] == "client" for case in manifest["cases"])
    engine_count = sum(case["contract"] == "engine" for case in manifest["cases"])
    print(
        f"PASS: {client_count} client cases, {engine_count} engine cases, "
        f"{len(covered)}/{len(known)} normative requirements covered, "
        "all vectors resolved, mandatory skips forbidden"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
