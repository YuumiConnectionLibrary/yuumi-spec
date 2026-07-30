# Yuumi Client Conformance Contract

Status: **alpha**

Wire protocol: **version `1`**

This is the executable acceptance contract for the Go client and listener. Its
normative sources are [`PROTOCOL.md`](./PROTOCOL.md) and
[`CLIENT_API.md`](./CLIENT_API.md). If this document or the machine-readable
manifest disagrees with either source, the normative source wins and the
conformance artifact must be corrected.

The complete case definitions are in
[`conformance/manifest.json`](./conformance/manifest.json). The manifest does
not define protocol behaviour. It identifies the normative requirements and
canonical vectors exercised by each case and declares deterministic expected
wire, API, cleanup, platform, and failure-evidence results.

---

## 1. Endpoint under test

Every `CC-*` case tests `go_client_listener`:

- Go validates configuration and derives the address before transport access;
- Go creates, protects, probes, accepts on, and cleans up the endpoint;
- the harness peer is a private engine dialer and is not a public non-Go client;
- listening is distinct from an established session;
- rejection of a candidate does not consume the single session slot; and
- session loss returns the same Go object to listening without process spawn,
  restart, discovery, or supervision.

The harness can split stream reads and writes at every byte, inject transport
and dispatch failures, observe attempted allocation and resource ownership,
block application handlers, and advance bounded virtual deadlines. Harness
seams are test-only and are not additions to the Client API.

---

## 2. Case structure

Each manifest case explicitly declares:

- stable case ID and covered normative requirement IDs;
- endpoint under test;
- preconditions;
- canonical vectors and deterministic constructed input;
- action;
- expected wire result;
- expected public API result;
- expected cleanup;
- applicable platforms and mandatory status; and
- readable failure evidence.

Application payloads are opaque. A case may select a protocol channel and a
scalar, list, map, JSON value, or MessagePack value, but it cannot require an
application envelope or fields named `cmd` or `data`.

---

## 3. Canonical Client cases

| ID | Acceptance boundary |
|---|---|
| `CC-001` | Configuration and address validation have no side effects |
| `CC-002` | Construction, token generation, and `Decode` are pure and typed |
| `CC-003` | `Open` protects the listener before traffic |
| `CC-004` | Endpoint liveness and stale cleanup are deterministic |
| `CC-005` | `listening` and `connected` are distinct states |
| `CC-006` | Invalid candidates do not consume the slot |
| `CC-007` | Exactly one session is established |
| `CC-008` | Go sends the exact handshake and validates ACK plus assignment |
| `CC-009` | Encoding and capability negotiation are exact |
| `CC-010` | Frames, bounds, fragmentation, and Control decode defensively |
| `CC-011` | Correlation and messages route without overlap |
| `CC-012` | Heartbeat and IPC progress while handlers are slow |
| `CC-013` | Bounded queues fail terminally on backpressure |
| `CC-014` | Session loss returns to listening without process policy |
| `CC-015` | `Close` is permanent, idempotent, and leak-free |
| `CC-016` | A new epoch rejects every stale authority |
| `CC-017` | The executable public surface is client-only and schema-free |
| `CC-018` | Every Client error kind is distinguishable |

The table is a human index. The manifest contains the executable inputs and
oracles; `tools/conformance_tool.py --coverage` emits the exact flat mapping
from every `PROTO-*` and `CLI-*` requirement to one or more cases.

---

## 4. Platform execution

Every Client case is mandatory on all three platforms. Platform-specific
assertions retain the same logical case ID and change only their native probe:

| Platform | Required evidence |
|---|---|
| Windows | Local and CI execution; byte-stream Named Pipe, intended-user ACL, remote rejection, handle cleanup |
| Linux | WSL and CI execution; Unix domain stream socket, mode `0600`, refused-stale unlink, node cleanup |
| macOS | CI during development and final real-hardware run; Unix socket security and exact 103/104-byte pathname boundary |

A required case cannot be marked skipped. Harness results use `pass`, `fail`,
or `skip`; `tools/conformance_tool.py --results <file>` rejects `skip` for any
mandatory case and rejects missing results. `--self-test` proves that guard by
feeding it a synthetic mandatory skip and requiring rejection.

---

## 5. Validation

Run:

```text
python tools/vector_tool.py
python tools/conformance_tool.py --self-test
python tools/conformance_tool.py --coverage
```

The checks fail for duplicate IDs, missing case fields, an unknown requirement,
an uncovered normative ID, a missing vector or annotation, a non-dialer Engine
endpoint, a non-listener Client endpoint, an omitted platform, a non-mandatory
case, a mandatory skip, or a non-opaque/application-shaped payload contract.

Task 15 supplies the SDK-specific executable harnesses and result files. This
contract supplies their deterministic inventory and oracles; it does not
implement SDKs, benchmarks, process lifecycle, or application schemas.
