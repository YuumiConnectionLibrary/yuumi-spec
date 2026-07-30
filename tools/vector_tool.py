#!/usr/bin/env python3

import argparse
import hashlib
import json
import pathlib
import re
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
VECTOR_DIR = ROOT / "test-vectors"
ADDRESS_PATH = VECTOR_DIR / "address_derivation.json"
MANIFEST_PATH = VECTOR_DIR / "manifest.json"
ENDPOINT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", re.ASCII)
TOKEN_RE = re.compile(r"[0-9a-f]{32}", re.ASCII)
MACOS_PATH_LIMIT = 103

ADDRESS_CASES = (
    {
        "id": "minimum_input",
        "endpoint_name": "a",
        "token": "000102030405060708090a0b0c0d0e0f",
        "temp_dir": "/tmp",
        "digest": "c3da2f7decb02b7a24e054711453a85c",
        "expected": "accept",
    },
    {
        "id": "maximum_input",
        "endpoint_name": "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
        "token": "f0e0d0c0b0a090807060504030201000",
        "temp_dir": "/tmp",
        "digest": "a9ce40da7198349aab024f107b698ef4",
        "expected": "accept",
    },
    {
        "id": "different_token",
        "endpoint_name": "a",
        "token": "100102030405060708090a0b0c0d0e0f",
        "temp_dir": "/tmp",
        "digest": "8710f11234486007b59a4333c6f01736",
        "expected": "accept",
    },
    {
        "id": "different_name",
        "endpoint_name": "b",
        "token": "000102030405060708090a0b0c0d0e0f",
        "temp_dir": "/tmp",
        "digest": "4c724cfb8212cb82d0857d699cdc7647",
        "expected": "accept",
    },
    {
        "id": "macos_long_temp_dir",
        "endpoint_name": "a",
        "token": "000102030405060708090a0b0c0d0e0f",
        "temp_dir": "/private/var/folders/aa/" + "b" * 33 + "/T",
        "digest": "c3da2f7decb02b7a24e054711453a85c",
        "expected": "accept",
    },
    {
        "id": "macos_path_over_limit",
        "endpoint_name": "a",
        "token": "000102030405060708090a0b0c0d0e0f",
        "temp_dir": "/private/var/folders/aa/" + "b" * 34 + "/T",
        "digest": "c3da2f7decb02b7a24e054711453a85c",
        "expected": "configuration_error_before_transport",
    },
)

INVALID_CASES = (
    {"id": "empty_name", "endpoint_name": "", "token": "0" * 32},
    {"id": "name_too_long", "endpoint_name": "a" * 33, "token": "0" * 32},
    {"id": "invalid_name_prefix", "endpoint_name": "_a", "token": "0" * 32},
    {"id": "invalid_name_character", "endpoint_name": "a.b", "token": "0" * 32},
    {"id": "token_too_short", "endpoint_name": "a", "token": "0" * 31},
    {"id": "uppercase_token", "endpoint_name": "a", "token": "A" * 32},
    {"id": "non_hex_token", "endpoint_name": "a", "token": "g" * 32},
)


def render_json(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def validate_inputs(endpoint_name, token):
    if ENDPOINT_RE.fullmatch(endpoint_name) is None:
        raise ValueError("invalid endpoint_name")
    if TOKEN_RE.fullmatch(token) is None:
        raise ValueError("invalid token")


def derive_digest(endpoint_name, token):
    validate_inputs(endpoint_name, token)
    source = b"yuumi\x00" + endpoint_name.encode("utf-8")
    source += b"\x00" + token.encode("utf-8")
    return hashlib.sha256(source).hexdigest()[:32]


def unix_address(temp_dir, digest):
    return temp_dir.rstrip("/") + "/yuumi-" + digest + ".sock"


def windows_address(endpoint_name, token):
    return "\\\\.\\pipe\\yuumi-" + endpoint_name + "-" + token


def address_fixture():
    cases = []
    for definition in ADDRESS_CASES:
        digest = derive_digest(definition["endpoint_name"], definition["token"])
        if digest != definition["digest"]:
            raise AssertionError(
                f"{definition['id']}: digest {digest} != pinned {definition['digest']}"
            )
        unix_path = unix_address(definition["temp_dir"], digest)
        path_bytes = len(unix_path.encode("utf-8"))
        actual = "accept" if path_bytes <= MACOS_PATH_LIMIT else "configuration_error_before_transport"
        if actual != definition["expected"]:
            raise AssertionError(
                f"{definition['id']}: macOS outcome {actual} != {definition['expected']}"
            )
        cases.append(
            {
                "id": definition["id"],
                "input": {
                    "endpoint_name": definition["endpoint_name"],
                    "token": definition["token"],
                    "os_temp_dir": definition["temp_dir"],
                },
                "expected": {
                    "digest": digest,
                    "windows_address": windows_address(
                        definition["endpoint_name"], definition["token"]
                    ),
                    "unix_filename": f"yuumi-{digest}.sock",
                    "unix_address": unix_path,
                    "unix_address_utf8_bytes": path_bytes,
                    "macos_outcome": definition["expected"],
                },
            }
        )

    invalid = []
    for definition in INVALID_CASES:
        try:
            validate_inputs(definition["endpoint_name"], definition["token"])
        except ValueError as error:
            invalid.append(
                {
                    "id": definition["id"],
                    "input": {
                        "endpoint_name": definition["endpoint_name"],
                        "token": definition["token"],
                    },
                    "expected": "configuration_error_before_transport",
                    "reason": str(error),
                }
            )
        else:
            raise AssertionError(f"{definition['id']}: invalid input was accepted")

    return {
        "description": "Canonical cross-SDK endpoint address derivation vectors.",
        "classification": "new",
        "normative_source": "PROTOCOL.md section 2.1",
        "algorithm": {
            "digest_input": "UTF-8(yuumi) || 0x00 || UTF-8(endpoint_name) || 0x00 || UTF-8(token)",
            "digest": "first 32 lowercase hexadecimal characters of SHA-256",
            "unix_filename": "yuumi-<digest>.sock",
            "windows_address": "\\\\.\\pipe\\yuumi-<endpoint_name>-<token>",
            "macos_max_path_bytes_excluding_nul": MACOS_PATH_LIMIT,
        },
        "cases": cases,
        "invalid_cases": invalid,
    }


def wire_reason(name):
    if name.startswith("handshake_"):
        return "Protocol version and 16-byte handshake layout are unchanged."
    if name.startswith("ack_"):
        return "The 4-byte ACK layout and capability intersection are unchanged."
    if name.startswith("control_"):
        return "Control framing and JSON payload bytes are unchanged."
    if name.startswith("frame_fragment_"):
        return "Fragmentation and prefix ordering bytes are unchanged."
    if name.startswith("frame_correlated_"):
        return "Correlation framing and identifiers are unchanged."
    return "Frame layout, channel, flags, encoding, and limits are unchanged."


def build_manifest():
    entries = []
    for binary in sorted(VECTOR_DIR.glob("*.bin")):
        annotation = binary.with_suffix(".json")
        if not annotation.exists():
            raise AssertionError(f"missing annotation for {binary.name}")
        note_bytes = annotation.read_bytes()
        note = json.loads(note_bytes)
        entries.append(
            {
                "file": binary.name,
                "size": binary.stat().st_size,
                "sha256": sha256_bytes(binary.read_bytes()),
                "annotation": annotation.name,
                "annotation_size": annotation.stat().st_size,
                "annotation_sha256": sha256_bytes(note_bytes),
                "classification": "unchanged",
                "reason": wire_reason(binary.name),
                "purpose": note["description"],
            }
        )
    address_bytes = ADDRESS_PATH.read_bytes()
    return {
        "description": "Canonical fixture inventory after listener ownership inversion.",
        "generated_by": "tools/vector_tool.py --write",
        "summary": {
            "unchanged_wire_binaries": len(entries),
            "modified_wire_binaries": 0,
            "new_wire_binaries": 0,
            "removed_wire_binaries": 0,
            "new_address_fixtures": 1,
        },
        "wire_vectors": entries,
        "address_vectors": [
            {
                "file": ADDRESS_PATH.name,
                "size": len(address_bytes),
                "sha256": sha256_bytes(address_bytes),
                "classification": "new",
                "reason": "Task 01 introduced canonical compact Unix address derivation and byte limits.",
            }
        ],
    }


def validate_wire_vectors(errors):
    binaries = sorted(VECTOR_DIR.glob("*.bin"))
    annotations = {
        path for path in VECTOR_DIR.glob("*.json") if path not in {ADDRESS_PATH, MANIFEST_PATH}
    }
    for binary in binaries:
        annotation = binary.with_suffix(".json")
        if annotation not in annotations:
            errors.append(f"missing annotation: {annotation.name}")
            continue
        try:
            note = json.loads(annotation.read_text(encoding="utf-8"))
            expected = bytes.fromhex(note["packet"]["hex"])
            declared_size = note["packet"]["size_bytes"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            errors.append(f"invalid annotation {annotation.name}: {error}")
            continue
        actual = binary.read_bytes()
        if actual != expected:
            errors.append(f"byte mismatch: {binary.name} != {annotation.name} packet.hex")
        if len(actual) != declared_size:
            errors.append(
                f"size mismatch: {binary.name} has {len(actual)}, annotation declares {declared_size}"
            )
        annotations.remove(annotation)
    for annotation in sorted(annotations):
        errors.append(f"orphan wire annotation: {annotation.name}")

    handshake = (VECTOR_DIR / "handshake_valid.bin").read_bytes()
    if len(handshake) != 16 or int.from_bytes(handshake[4:8], "big") != 1:
        errors.append("handshake_valid.bin must encode protocol version 1 in 16 bytes")


def check_exact(path, expected, errors):
    if not path.exists():
        errors.append(f"missing generated fixture: {path.relative_to(ROOT)}")
        return
    actual = path.read_bytes()
    if actual != expected:
        errors.append(
            f"generated fixture differs: {path.relative_to(ROOT)}; run tools/vector_tool.py --write"
        )


def write_generated():
    VECTOR_DIR.mkdir(parents=True, exist_ok=True)
    ADDRESS_PATH.write_bytes(render_json(address_fixture()))
    MANIFEST_PATH.write_bytes(render_json(build_manifest()))
    print(f"wrote {ADDRESS_PATH.relative_to(ROOT)}")
    print(f"wrote {MANIFEST_PATH.relative_to(ROOT)}")


def check_all():
    errors = []
    expected_address = render_json(address_fixture())
    check_exact(ADDRESS_PATH, expected_address, errors)
    if ADDRESS_PATH.exists() and ADDRESS_PATH.read_bytes() == expected_address:
        expected_manifest = render_json(build_manifest())
        check_exact(MANIFEST_PATH, expected_manifest, errors)
    validate_wire_vectors(errors)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    print(
        "PASS: "
        f"{manifest['summary']['unchanged_wire_binaries']} exact wire vectors unchanged, "
        f"{len(address_fixture()['cases'])} address cases, "
        f"{len(address_fixture()['invalid_cases'])} invalid-input cases"
    )
    return 0


def print_inventory():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    print("file\tsize\tsha256\tclassification\tpurpose")
    for entry in manifest["wire_vectors"]:
        print(
            f"{entry['file']}\t{entry['size']}\t{entry['sha256']}\t"
            f"{entry['classification']}\t{entry['purpose']}"
        )
    for entry in manifest["address_vectors"]:
        print(
            f"{entry['file']}\t{entry['size']}\t{entry['sha256']}\t"
            f"{entry['classification']}\tCanonical address derivation"
        )


def main():
    parser = argparse.ArgumentParser(description="Generate and validate Yuumi canonical fixtures.")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--write", action="store_true", help="write deterministic generated fixtures")
    action.add_argument("--inventory", action="store_true", help="print the generated inventory")
    args = parser.parse_args()
    if args.write:
        write_generated()
        return check_all()
    if args.inventory:
        print_inventory()
        return 0
    return check_all()


if __name__ == "__main__":
    raise SystemExit(main())
