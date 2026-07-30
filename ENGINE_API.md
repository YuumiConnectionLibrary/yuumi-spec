# Yuumi Engine API Contract

Status: **alpha**

Wire protocol: **version `1`**

This document is the normative, language-neutral contract for the C++, Python,
Rust, and TypeScript engine SDKs. The keywords **MUST**, **MUST NOT**,
**SHOULD**, **SHOULD NOT**, and **MAY** are normative.

The Engine API is intentionally different from the Go
[Client API](./CLIENT_API.md). An engine is always a single-session dialer. It
never owns an endpoint, listens, accepts candidates, starts another process, or
implements reconnection policy. Public names may be idiomatic, but the
observable behaviour identified below is mandatory.

---

## 1. Responsibilities and public boundary

- **ENG-ROLE-001** — The application supplies `endpoint_name` and `token`.
- **ENG-ROLE-002** — The engine validates configuration, derives the canonical
  address, dials the Go listener, receives and validates the handshake,
  negotiates encoding and capabilities, writes ACK and session assignment, and
  owns framing, correlation, fragmentation, heartbeat, and cleanup for that
  connection.
- **ENG-ROLE-003** — The engine **MUST NOT** bind, listen, accept, probe or
  remove stale endpoints, alter endpoint security, or expose an arbitrary
  transport address.
- **ENG-ROLE-004** — Spawn, restart, discovery, supervision, executable
  selection, and stdout/stderr capture are application responsibilities. No
  engine `Runner` or equivalent belongs to this contract.
- **ENG-ROLE-005** — No public client API may be exposed by an engine SDK. A
  private Go-role peer is permitted only inside `testkit/` or tests.

---

## 2. Configuration

An engine is constructed from an explicit configuration value:

| Field | Normative behaviour |
|---|---|
| **ENG-CFG-001** `endpoint_name` | Required and validated exactly as specified by `PROTOCOL.md`. |
| **ENG-CFG-002** `token` | Required; exactly 32 lowercase hexadecimal characters. |
| **ENG-CFG-003** `supported_encodings` | Ordered, non-empty, duplicate-free preference. Default: MessagePack, then JSON. |
| **ENG-CFG-004** `supported_capabilities` | Default: `CAP_CORRELATION`. Reserved or unimplemented bits are rejected. Every version 1 engine implements correlation. |
| **ENG-CFG-005** `expected_go_pid` | Optional additional check. Absence and zero are distinct. It is not primary authentication. |
| **ENG-CFG-006** `connect_timeout` | Optional positive duration. Default: 10 s for the complete dial and handshake attempt; it never means infinite waiting. |
| **ENG-CFG-007** `application_queue_capacity` | Optional positive integer. Default: **64** application events. |
| **ENG-CFG-008** heartbeat | Optional `disabled`, positive interval, and positive miss limit. Omitted values use protocol recommendations; the boolean is `disabled`, not `enabled`. |
| **ENG-CFG-009** fragmentation | Optional positive timeout and active-sequence limit. Defaults: 15 s and 16. The 16 MiB protocol bounds are fixed. |

- **ENG-CFG-010** — Invalid configuration or address derivation fails before
  dialing.
- **ENG-CFG-011** — Configuration is copied or frozen when `connect` starts and
  remains immutable until the attempt has completely returned to `idle`.
  Mutation of the caller's original value has no effect.
- **ENG-CFG-012** — There is no `max_sessions`, retry count, reconnect delay,
  arbitrary address, listener, or process-lifecycle option.

---

## 3. Required behavioural surface

The required behavioural surface consists of these operations or direct
language-native equivalents:

| Operation | Normative behaviour |
|---|---|
| **ENG-API-001** create engine | Stores explicit configuration and performs no transport operation. |
| **ENG-API-002** `connect` | Performs one dial and handshake attempt. It succeeds only after session assignment has been written and the session is usable; otherwise it returns one typed error. It never retries automatically. |
| **ENG-API-003** `close` | Rejects new work, tears down the attempt or session, releases all engine-owned resources, and is idempotent. |
| **ENG-API-004** `send` | Sends an opaque payload on an engine-output application channel under the current epoch. Control traffic is not public. |
| **ENG-API-005** `respond` | Uses the responder attached to a correlated inbound message, repeats its channel and correlation ID, is valid at most once, and requires negotiated `CAP_CORRELATION`. |
| **ENG-API-006** events | Makes connected, message, heartbeat, error, and disconnected events observable. Pull streams, iterators, channels, or callbacks are valid idiomatic forms. |
| **ENG-API-007** session view | Exposes immutable `session_id`, opaque local epoch, selected encoding, and negotiated capabilities while connected. |
| **ENG-API-008** terminal result | Makes the terminal reason for an established session observable even if event delivery itself caused termination. |

Payloads are opaque protocol values: the SDK encodes and decodes them using the
negotiated codec but imposes no application schema. A message event contains
the channel, payload, optional correlation ID, captured epoch, and an optional
single-use responder. A responder is absent for uncorrelated messages.

- **ENG-API-009** — Public sends accept only `Log` and `Data`. Received
  application traffic accepts only `Command` and `Data`.
- **ENG-API-010** — A completed `send` means its frame bytes were written. An
  implementation that queues writes may return an awaitable/future, but must
  not report success before the write result is known.
- **ENG-API-011** — Sequentially submitted sends preserve submission order.
  Concurrent sends are serialized in a documented runtime-native order.
- **ENG-API-012** — A send fails before wire output when no session exists, the
  epoch is stale, direction is invalid, correlation is unavailable,
  serialization fails, or a size bound would be exceeded.

### 3.1 Optional environment adapter

- **ENG-ENV-001** — An SDK **MAY** provide a separate adapter that reads
  `YUUMI_ENDPOINT_NAME` and `YUUMI_TOKEN` and returns an `EngineConfig`.
- **ENG-ENV-002** — The adapter performs no dial, listener, spawn, discovery,
  retry, or supervision action. Missing or invalid variables are configuration
  errors. Explicit constructor arguments remain the fundamental API.

---

## 4. Normative state machine

```text
             connect
    +------+ ---------> +------------+
    | idle |            | connecting |
    +------+ <--------- +------------+
       ^       failure        |
       |                      | ACK + session assignment written
       |                      v
       |                 +-----------+
       +---------------- | connected |
       | terminal close  +-----------+
       |                      |
       | close                | close / terminal failure
       |                      v
       |                 +---------+
       +---------------- | closing |
                         +---------+
```

| State | Invariant |
|---|---|
| **ENG-STATE-001** `idle` | No connection or session is owned. |
| **ENG-STATE-002** `connecting` | Dial or handshake is in progress. A second `connect` fails with `already_connecting`; it neither joins nor cancels the first attempt. |
| **ENG-STATE-003** `connected` | Session assignment is complete and application operations are permitted. A second `connect` fails with `already_connected`. |
| **ENG-STATE-004** `closing` | New application operations fail with `session_closed`; resources and dispatch are being drained. |
| **ENG-STATE-005** terminal transition | Completion of close or any terminal connect/session failure returns the engine to `idle`. |

- **ENG-STATE-006** — `close` is valid in every state. In `connecting`, it
  cancels dial/handshake and `connect` returns `session_closed` with the
  local-close cause. In `idle`, it succeeds without side effects.
- **ENG-STATE-007** — Reconnection is never automatic. After return to `idle`,
  only a new application call to `connect` begins another attempt.
- **ENG-STATE-008** — Every successful connection creates a new printable
  `session_id` and a local epoch strictly greater than the previous successful
  epoch for that engine object. Epoch zero means “no session”.
- **ENG-STATE-009** — Fragment buffers, heartbeat state, correlations, queued
  sends, responders, timers, and callbacks capture an epoch. Old work fails
  with `stale_epoch` or is discarded and can neither emit against, write to,
  mutate, nor close a replacement session.

---

## 5. Dial and establishment

- **ENG-CONN-001** — Before dialing, the engine validates configuration,
  derives the exact platform address from `PROTOCOL.md`, and validates Unix
  pathname bytes including the macOS 103-byte limit.
- **ENG-CONN-002** — Linux and macOS use a Unix domain stream socket. Windows
  uses a byte-stream Named Pipe. TCP and transport fallback are forbidden.
- **ENG-CONN-003** — Refused, absent, denied, busy, and timed-out endpoints
  produce distinguishable dial/timeout causes. The engine never treats any of
  them as authority to create or remove an endpoint.
- **ENG-CONN-004** — The engine reads exactly 16 handshake bytes before
  parsing, validates magic/version/PID policy, selects the first configured
  encoding in the intersection, and intersects implemented capabilities.
- **ENG-CONN-005** — Invalid magic, version, PID, empty encoding intersection,
  short read, or pre-ACK transport failure closes without ACK or framed error.
- **ENG-CONN-006** — On success the engine writes the exact 4-byte ACK,
  generates a new session ID, writes the session Control frame immediately
  afterward, then enters `connected` and emits connected.
- **ENG-CONN-007** — ACK or session-assignment write failure never creates a
  session and therefore emits neither connected nor disconnected.

---

## 6. Dispatch, callbacks, and backpressure

Transport reads, frame parsing, writes, heartbeat, fragment expiry, and close
form the IPC path. Application delivery forms a separate serial dispatch path.

- **ENG-DISP-001** — The IPC path never invokes application logic directly and
  never waits indefinitely for application delivery.
- **ENG-DISP-002** — For one epoch, application events are delivered in wire
  order and handler invocations never overlap. Lifecycle order is `connected`,
  zero or more message/heartbeat/error events, then one `disconnected`.
- **ENG-DISP-003** — No callback runs while holding a lock required by a public
  operation. Closing wakes transport waits and dispatcher waits.
- **ENG-DISP-004** — The bounded application queue has configured capacity,
  default 64. Two internal terminal slots are reserved for a backpressure error
  and disconnection and do not increase advertised application capacity.
- **ENG-DISP-005** — If the application capacity is full, the SDK stops
  accepting application work, records `backpressure` as terminal cause, closes
  the session, drains accepted events in order, then delivers the reserved
  backpressure error and disconnected event. It never drops an event and
  continues as if successful.
- **ENG-DISP-006** — Once closing begins, no new message or heartbeat event is
  accepted. No callback for an epoch begins after its disconnected event.
- **ENG-DISP-007** — If a callback throws, rejects, panics, or otherwise fails,
  the SDK catches it at the dispatch boundary and produces an observable
  `application` error; it is never successful delivery. Failure in the error
  observer is reported once through the runtime-native uncaught-handler
  facility and is not recursively dispatched.
- **ENG-DISP-008** — TypeScript uses distinct event-loop turns: parsing,
  heartbeat, and close must advance between callbacks. Synchronous CPU-bound
  user code still blocks JavaScript and is application responsibility.

---

## 7. Session cleanup and correlation

- **ENG-SESS-001** — Disconnect clears fragments, correlations, timers,
  negotiated state, queued sends, and responder authority before `idle`.
- **ENG-SESS-002** — A responder is bound to `(epoch, channel,
  correlation_id)`, is single-use, and becomes stale on disconnect or timeout.
- **ENG-SESS-003** — Correlated input without negotiated
  `CAP_CORRELATION` is a protocol error. Application response payloads,
  including application errors, never become protocol Control errors.
- **ENG-SESS-004** — Fatal protocol errors that can be safely framed send one
  Control error and then close. Unsafe framing failures close without output.
- **ENG-SESS-005** — `close` is idempotent, stops/cancels all engine-owned work,
  unblocks waiters, and never removes or modifies the Go-owned endpoint.

---

## 8. Error model

Every failure exposes a stable kind plus an English cause. It also carries the
protocol status and phase where applicable, and the epoch only for an
established session.

| Kind | Produced when |
|---|---|
| **ENG-ERR-001** `configuration` | A configuration value is absent, malformed, duplicated, reserved, zero where positive is required, or unsupported. |
| **ENG-ERR-002** `address_derivation` | Platform temp lookup, filesystem encoding, hashing, or socket-path byte validation fails. |
| **ENG-ERR-003** `dial` | The endpoint is absent, refused, denied, busy beyond attempt policy, or platform dial fails. |
| **ENG-ERR-004** `timeout` | Connect, read, write, request, heartbeat, or fragment deadline expires; phase distinguishes them. |
| **ENG-ERR-005** `handshake` | Handshake length, magic, version, PID, ACK write, or assignment write fails. |
| **ENG-ERR-006** `protocol` | Framing, channel, flag, Control, correlation, fragmentation, or state violates `PROTOCOL.md`. |
| **ENG-ERR-007** `encoding` | No encoding intersects or codec processing fails. |
| **ENG-ERR-008** `capability` | Configuration enables an unsupported bit or an operation needs an unnegotiated capability. |
| **ENG-ERR-009** `backpressure` | The application queue is exhausted; terminal for that session. |
| **ENG-ERR-010** `session_closed` | An operation has no live session or closing cancels it. |
| **ENG-ERR-011** `stale_epoch` | Work captured for an earlier epoch attempts to act. |
| **ENG-ERR-012** `application` | An application callback/handler fails. |
| **ENG-ERR-013** `transport` | Established read/write/close fails independently of a deadline. |
| **ENG-ERR-014** `internal` | An invariant or runtime facility fails and no specific kind applies. |
| **ENG-ERR-015** `state` | Duplicate connect or another operation is invalid for the current non-closed state. |

Failed candidates have no epoch. Established terminal errors are reported once
and remain the terminal result; disconnected is not a success replacement.

---

## 9. Idiomatic implementation and migration matrix

| Behaviour | C++ | Python | Rust | TypeScript |
|---|---|---|---|---|
| Engine/config | `Engine(EngineConfig)` | `Engine(EngineConfig)` | `Engine::new(EngineConfig)` | `new Engine(EngineConfig)` |
| Connect | `Result<SessionView> connect()` | `connect() -> SessionView` | `async fn connect(&self) -> Result<SessionView>` | `connect(): Promise<SessionView>` |
| Close | `Result<> close()` | `close() -> None` | `async fn close(&self) -> Result<()>` | `close(): Promise<void>` |
| Send | `Result<> send(Channel, Json)` | `send(Channel, Any)` | `async fn send<T: Serialize>(...)` | `send(channel, payload): Promise<void>` |
| Respond | epoch-bound `Responder::respond` | epoch-bound `Responder.respond` | epoch-bound `Responder::respond` | epoch-bound `Responder.respond` |
| Events | serial dispatcher or pull queue | explicit daemon dispatcher thread and bounded `queue.Queue` | bounded channel; callbacks remain `Arc<dyn Fn + Send + Sync>` | bounded logical queue across event-loop turns |
| Session view | immutable value | frozen dataclass | immutable owned struct | frozen/readonly object |
| Environment adapter | free config factory | module config factory | free config function | exported config function |
| Constraint | existing header/runtime model | `ctypes` Named Pipe dialer; no native install build | no async closures; stable futures and `Arc` callbacks | no runtime dependency beyond MessagePack codec |

### 9.1 Current public API disposition

| SDK | Keep or adapt | Replace | Remove from public API |
|---|---|---|---|
| C++ | `Engine`, `EngineConfig`, `close`, send/event/error/session types | `open()` -> `connect()`; handle sends -> current-session send/responder; listener phases -> dial phases | `ServerBridge`, `Bridge`, `max_sessions`, listener/accept/endpoint ownership, public address helper |
| Python | `Engine`, typed config/events/errors, `close`, send concepts | `open()` -> `connect()`; mutable config -> frozen snapshot; handle sends -> current-session send/responder | `max_sessions`, listener/accept classes and phases, endpoint cleanup, public address helper |
| Rust | `Engine`, `EngineConfig`, `Result`, `Arc<dyn Fn + Send + Sync>` callbacks | `open().await` -> `connect().await`; handle sends -> current-session send/responder | `max_sessions`, listener/accept tasks and phases, endpoint cleanup, public address helper |
| TypeScript | `Engine`, immutable config, promises, typed events | `open()` -> `connect()`; handle sends -> current-session send/responder | `maxSessions`, listener/server creation, endpoint probe/removal, public address helper |

Transport-address helpers may remain internal or test-only. Listener aliases
and compatibility shims are not conforming public API; removal may require the
next library-major release, but the target surface is unambiguous.

---

## 10. Conformance trace

The [`Engine Conformance Contract`](./ENGINE_CONFORMANCE.md) and
[`conformance/manifest.json`](./conformance/manifest.json) supply one common
executable inventory for C++, Python, Rust, and TypeScript. Every `EC-*` case
names `engine_dialer` as its endpoint under test. The manifest references every
concrete `ENG-*` identifier; its exact flat mapping is validated and can be
printed with:

```text
python tools/conformance_tool.py --coverage
```

The mapping is generated instead of maintained as wildcard ranges in two
documents. Validation fails if a requirement is missing, an ID is duplicated,
a vector does not exist, a platform is omitted, or a mandatory case can be
skipped. No case requires a Python native installation build, an unstable Rust
async closure, or a TypeScript runtime dependency beyond the MessagePack codec.
