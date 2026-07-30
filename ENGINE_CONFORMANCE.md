# Yuumi Engine Conformance Contract

Status: **alpha**

Wire protocol: **version `1`**

This is the common executable acceptance contract for the C++, Python, Rust,
and TypeScript engine SDKs. Its normative sources are
[`PROTOCOL.md`](./PROTOCOL.md) and [`ENGINE_API.md`](./ENGINE_API.md). If this
document or the machine-readable manifest disagrees with either source, the
normative source wins and the conformance artifact must be corrected.

The complete case definitions are in
[`conformance/manifest.json`](./conformance/manifest.json). The manifest is an
execution index, not a second protocol specification: it references stable
normative IDs and frozen vectors and records the observable oracle for each
case.

---

## 1. Endpoint under test

Every `EC-*` case tests `engine_dialer` in each of the four engine SDKs:

- Linux and macOS dial the exact Unix domain stream socket;
- Windows dials the exact byte-stream Named Pipe;
- the private harness peer owns the Go-role listener and sends the handshake;
- the engine returns ACK and session assignment;
- the engine never binds, listens, accepts, probes or removes an endpoint,
  changes endpoint security, or falls back to TCP; and
- reconnection occurs only after a new application call to `connect`.

The harness listener is test infrastructure. It cannot become public engine
API or a public non-Go client. It can split bytes at every boundary, inject
dial/read/write/close failures, observe allocation and endpoint mutation,
block handlers, and advance bounded virtual deadlines.

---

## 2. Case structure

Each manifest case explicitly declares:

- stable case ID and covered normative requirement IDs;
- `engine_dialer` as the endpoint under test;
- preconditions;
- canonical vectors and deterministic constructed input;
- action;
- expected wire result;
- expected public API result;
- expected cleanup;
- Windows, Linux, and macOS applicability with mandatory status; and
- readable failure evidence.

Application payloads are opaque. The harness may choose a protocol channel and
an encodable scalar, list, map, JSON value, or MessagePack value, but cannot
require an application envelope or fields named `cmd` or `data`.

---

## 3. Canonical Engine cases

| ID | Acceptance boundary |
|---|---|
| `EC-001` | Configuration validation is pure and snapshot-based |
| `EC-002` | Canonical address derivation is byte-identical |
| `EC-003` | Every engine is only a platform-native dialer |
| `EC-004` | Dial failures are explicit and grant no endpoint ownership |
| `EC-005` | Handshake is exact and invalid input writes nothing |
| `EC-006` | Encoding and capability intersection are deterministic |
| `EC-007` | ACK and session assignment establish in exact order |
| `EC-008` | Establishment write failure creates no session |
| `EC-009` | The state machine rejects duplicate `connect` |
| `EC-010` | `close` is idempotent and reconnect is explicit |
| `EC-011` | Frames and oversize bounds are exact |
| `EC-012` | Malformed frames never partially deliver |
| `EC-013` | Fragmentation is bounded and epoch-local |
| `EC-014` | Correlation preserves responder authority |
| `EC-015` | Public sends are directional, ordered, and await writes |
| `EC-016` | Control and fatal ordering are exact |
| `EC-017` | IPC progresses independently of slow handlers |
| `EC-018` | Backpressure is terminal and observable |
| `EC-019` | Callback failures and TypeScript turns are observable |
| `EC-020` | Disconnect clears session state before idle |
| `EC-021` | A replacement epoch rejects stale work |
| `EC-022` | Every Engine error kind is distinguishable |
| `EC-023` | Public surface has no listener, client, Runner, or schema policy |
| `EC-024` | Optional environment adapter is configuration-only |
| `EC-025` | Cleanup and runtime constraints hold for all four engines |

The table is a human index. `tools/conformance_tool.py --coverage` expands the
manifest patterns and emits the exact flat mapping from every `PROTO-*` and
`ENG-*` requirement to one or more cases.

---

## 4. Removed old-topology cases

The `legacy_cases_removed` section of the manifest records the source commit,
old ID, title, and reason for each listener-engine case removed from the
pre-inversion suite. The removed assertions are:

- engine `open` creating a listener;
- engine replacement of a live endpoint;
- engine stale-node or stale-handle cleanup;
- engine ownership of socket mode or Named Pipe ACL;
- engine cleanup of the listener endpoint;
- `max_sessions = 1` admission accounting;
- configurable `max_sessions = N`; and
- accept-loop failure isolation.

Role-correct requirements were not discarded. Endpoint security, liveness,
stale cleanup, single-session admission, and accept-loop cleanup moved to the
Go Client contract. Engine cases retain dial failure, one active engine object
session, explicit reconnect, per-epoch isolation, and engine-owned cleanup.

---

## 5. Platform and language matrix

Every Engine case is mandatory for C++, Python, Rust, and TypeScript on all
three platforms. A native assertion keeps the same `EC-*` ID:

| Platform | Required execution and transport evidence |
|---|---|
| Windows | Local and CI; byte-stream Named Pipe dial and deterministic handle cleanup |
| Linux | WSL and CI; Unix domain stream dial and deterministic descriptor cleanup |
| macOS | CI during development and final real-hardware run; Unix dial and exact path-byte boundary |

Language-specific runtime assertions remain part of the shared logical case:
Python uses an explicit daemon dispatcher and a `ctypes` Named Pipe shim; Rust
uses stable callback/future forms; TypeScript yields between callbacks so IPC
timers and close advance; C++ catches application exceptions at the dispatch
boundary.

No required case may be permanently skipped. Harness result validation rejects
both an explicit mandatory `skip` and a missing mandatory result.

---

## 6. Validation

Run:

```text
python tools/vector_tool.py
python tools/conformance_tool.py --self-test
python tools/conformance_tool.py --coverage
```

The checks fail for duplicate IDs, missing structure, unknown or uncovered
requirements, missing vectors or annotations, an endpoint under test other
than `engine_dialer`, platform omission, non-mandatory cases, mandatory skips,
or application-shaped payload requirements.

Task 15 supplies the per-SDK harness implementations and result files. This
contract supplies their deterministic inventory and oracles; it does not add
SDK implementation, process lifecycle, benchmarks, or application schemas.
