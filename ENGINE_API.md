# Yuumi Engine API Contract

Status: **alpha**

Wire protocol: **version `1`**

This document is the authoritative, language-neutral contract for Yuumi engine
SDKs. C++, Python, Rust, and TypeScript implement this role. The keywords
**MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are normative.

The Engine API is intentionally different from the Go Client API. It opens a
local endpoint, accepts connections from the Go shell, owns isolated sessions,
and exposes engine-side events and sends. A codec or an outbound dialer alone
does not satisfy this contract.

Names in this document describe operations and values, not mandatory language
spellings. Each SDK **MUST** expose the same observable behaviour through
idiomatic constructs for its language.

---

## 1. Engine configuration

An engine instance **MUST** accept the following configuration before its
endpoint is opened.

| Option | Contract |
|---|---|
| `endpoint_name` | Required. It **MUST** satisfy the validation and address-derivation rules in `PROTOCOL.md`. |
| `token` | Required. It **MUST** be exactly 32 lowercase hexadecimal characters and is part of the derived endpoint address. |
| `max_sessions` | Optional, default `1`. It **MUST** be an integer greater than zero. `1` preserves one-to-one operation; `N` permits at most `N` simultaneous established sessions. |
| `supported_encodings` | Optional ordered preference, default MessagePack then JSON. It **MUST** contain at least one distinct encoding supported by protocol version 1. |
| `supported_capabilities` | Optional bitmask, default `CAP_CORRELATION`. A conforming version 1 Engine API **MUST** implement `CAP_CORRELATION` and **MUST NOT** enable an unimplemented or reserved capability. |
| `expected_pid` | Optional unsigned 32-bit process identifier. Absence disables PID filtering. Zero is a PID value, not a sentinel for absence. |
| heartbeat settings | Optional interval and missed-interval limit. Values **MUST** be positive when heartbeat emission is enabled. The protocol recommendations are the defaults. |
| fragmentation settings | Optional timeout and active-sequence limit. Values **MUST** be positive and the 16 MiB protocol bounds remain mandatory. |

Invalid configuration **MUST** fail before the SDK creates, removes, or changes
an endpoint. Configuration that affects address derivation, security,
negotiation, or session capacity **MUST NOT** change while the endpoint is open.

---

## 2. Required Engine API surface

A conforming SDK **MUST** provide the following engine-side operations. It may
use methods, functions, builders, callbacks, events, streams, or language-native
equivalents, provided their observable behaviour is the same.

| Operation | Required behaviour |
|---|---|
| Open engine | Validate configuration, acquire the platform endpoint, apply security controls, and become ready to accept connections. Success means the endpoint is ready; it does not wait for a session. Opening an already-open engine **MUST** fail. |
| Close engine | Stop accepting, close every established session, finish their disconnect notifications, release resources, and remove or release the endpoint. Closing an already-closed engine **MUST** be safe. |
| Send message | Accept a live session handle, an engine-to-client application channel, and a payload. It sends an uncorrelated message using that session's negotiated encoding. |
| Send correlated message | Accept a live session handle, an engine-to-client application channel, a `uint32` correlation identifier, and a payload. It sends `FLAG_CORRELATED` only when the session negotiated `CAP_CORRELATION`. |
| Register or consume events | Deliver session connected, message, error, and session disconnected events with the ordering and data defined below. |

Control traffic is owned by the SDK. The application send surface **MUST NOT**
allow callers to forge session assignment, heartbeat, ping/pong, or protocol
error messages. It **MUST** reject unknown channels and directions forbidden to
the engine by the channel table in `PROTOCOL.md`.

An accepted send is scoped to exactly one session. A failure in one session
**MUST NOT** send the payload to another session or close unrelated sessions.
Calls accepted sequentially for the same session **MUST** reach the transport in
the same order. Concurrent-call ordering may follow the language's documented
concurrency model.

A send request **MUST** fail explicitly when the session is absent, closed, or
stale; the channel is invalid for engine output; correlation was not negotiated;
serialization fails; or a frame or reassembled message would exceed 16 MiB.
Acceptance may mean queued or written according to the language's idiom, but a
later transport failure **MUST** be surfaced through the error event.

---

## 3. Endpoint lifecycle

Opening the engine **MUST** perform these steps in order:

1. Validate all configuration.
2. Derive the canonical platform address from `endpoint_name` and `token`.
3. Probe an existing endpoint by attempting a connection.
4. Refuse to replace a live endpoint. Remove or release an endpoint only after
   the probe establishes that no live listener owns it.
5. Create a Unix domain stream socket on Linux/macOS or a byte-stream Named Pipe
   on Windows and apply the security controls in section 7 before accepting
   handshake traffic.
6. Begin accepting connections until close is requested.

Endpoint presence alone **MUST NOT** be treated as liveness. A busy Named Pipe
is not stale. On Unix, a refused stale socket node is unlinked before bind. On
Windows, stale server handles owned by the process are closed and the canonical
pipe name is recreated; no filesystem unlink is attempted.

Accepting a transport connection **MUST** reserve one of the `max_sessions`
slots before reading its handshake. Pre-session and established connections
together **MUST NOT** exceed the limit. A transport connection admitted when no
slot is available **MUST** be closed without an ACK or session event. Capacity
becomes available only after the failed handshake or established session has
been torn down completely.

During orderly close, the engine stops admitting connections before it tears
down established sessions. When close reports completion:

- no session callback may begin afterward;
- all transport and worker resources owned by the engine are stopped;
- every established session has emitted one disconnect event;
- all session state is discarded; and
- the Unix socket node or final Named Pipe server handle has been removed or
  released.

---

## 4. Engine-side handshake

Each accepted connection remains a pre-session connection until all steps in
this section succeed.

1. Read exactly 16 handshake bytes before parsing any field.
2. Validate magic and protocol version.
3. If `expected_pid` is present, compare it with the handshake PID and, where
   trustworthy peer credentials are available, verify those credentials as
   required by `PROTOCOL.md`.
4. Select the first configured encoding preference present in the client's
   encoding mask. Reject an empty intersection.
5. Compute `client_capabilities & supported_capabilities`, excluding every
   unknown or reserved bit.
6. Send the 4-byte ACK containing the selected encoding and exact capability
   intersection.
7. Allocate the session state and send its Control session message immediately
   after the ACK and before any other frame.
8. Mark the session established and emit its connected event.

Invalid magic, an incompatible version, an empty encoding intersection, or an
`expected_pid` mismatch **MUST** close the connection without emitting any ACK
bytes. A short handshake or transport failure before ACK emission also closes
without an ACK. An ACK write failure closes immediately; a partial transport
write is not a valid ACK. A failure after ACK but before session assignment
**MUST** close the connection without emitting a connected or disconnected
session event. Every failure **MUST** be observable through an error result or
error event with the applicable protocol status.

The engine **MUST NOT** send a framed Control error to a pre-session peer.

---

## 5. Sessions

Each successful handshake creates a new, isolated session. The session handle
visible to callbacks and send operations **MUST** identify both `session_id` and
`epoch`; a handle from an earlier generation **MUST NOT** address a later
session.

Each session owns at least this state:

| State | Required invariant |
|---|---|
| selected encoding | Exactly the value sent in the ACK; immutable for the session. |
| negotiated capabilities | Exactly the ACK intersection; immutable for the session. |
| heartbeat state | Timers, last activity, sequence/counters, and missed intervals are not shared with another session. |
| fragmentation state | Active buffers, identifiers, cumulative sizes, and deadlines are not shared with another session. |
| correlation state | Pending identifiers are not shared with another session. |
| `session_id` | A new non-empty printable ASCII value of at most 128 bytes, unique among active sessions and sent in the session Control message. |
| `epoch` | A local non-negative generation counter. The first established generation is `0`; every later established generation uses a greater value. It is never transmitted. |

An implementation may use connection slots or allocate fresh session objects.
If it reuses a slot or object, it **MUST** increment the generation before the
replacement session becomes visible. It **MUST** reject delayed sends, callbacks,
timeouts, fragments, and correlations carrying an older epoch.

A disconnection destroys the session's negotiated state, heartbeat state,
fragment buffers, and pending correlations. A later connection performs a full
handshake, receives a new `session_id` and epoch, and starts with empty state.
There is no session resumption.

---

## 6. Event contract

Events for one session **MUST** preserve the following order:

```text
session connected
zero or more message/error events
session disconnected
```

Events from different sessions may be interleaved or delivered concurrently.
Application events for the same session **MUST** be delivered serially. An SDK
**MUST** document the language-native execution context used for event delivery.

### 6.1 Session connected

The connected event fires exactly once after the ACK and session Control
message have both been written successfully. It provides an immutable session
view containing `session_id`, `epoch`, selected encoding, and negotiated
capabilities. A rejected handshake never produces this event.

### 6.2 Message

The message event fires once for each complete, valid, decoded non-Control
message. It provides:

- the live session handle;
- channel;
- decoded payload in the selected encoding; and
- the `correlation_id` when `FLAG_CORRELATED` is present, otherwise no
  correlation value.

Fragmented input is delivered only after successful reassembly. Control frames,
partial fragments, malformed payloads, direction violations, and protocol
errors **MUST NOT** be delivered as application messages.

### 6.3 Error

The error event provides the error category, applicable protocol status code,
phase, cause, and session handle when a session exists. Pre-session and endpoint
errors have no session handle. A terminal cause **MUST** be reported once; the
SDK **MUST NOT** replace an error with an empty payload, success result, or
normal disconnect reason.

After session establishment, a fatal protocol error **MUST** send the protocol
Control error when framing it is safe, then close that session. Endpoint-level
accept failures are reported without terminating healthy established sessions
unless the endpoint itself can no longer accept safely.

### 6.4 Session disconnected

The disconnected event fires exactly once for every session that emitted a
connected event. It includes the final session handle and a reason that
distinguishes orderly engine close, peer close, heartbeat timeout, protocol
failure, and transport failure. No message event for that session may begin
after its disconnected event.

Handshake rejection does not create a session and therefore produces neither a
connected nor a disconnected event.

---

## 7. Security contract

The engine **MUST** validate the configured token before endpoint creation and
derive the address with that exact token. The public API **MUST NOT** accept an
arbitrary full transport path in place of `endpoint_name` and `token`, because
that would bypass canonical derivation and token verification. The token
**SHOULD** be redacted from diagnostics.

Before accepting handshake traffic, the engine **MUST**:

- create a Linux/macOS socket node accessible only to its owner with mode
  `0600`; or
- create a Windows Named Pipe with an ACL restricted to the intended local
  user and reject remote clients.

`expected_pid` is an optional additional control, not authentication. When it
is absent, PID mismatch filtering is disabled. When it is present, a mismatch
closes without ACK and reports `ERR_PID_MISMATCH (402)`. The token and OS access
controls remain mandatory in both cases.

---

## 8. What the Engine API does not cover

Yuumi is the bridge, not application policy. This contract does not decide:

- who launches the engine process;
- who requests engine shutdown or when that happens;
- whether, when, or how the engine is restarted;
- command meaning, business rules, persistence, authorization, or any other
  application semantics; or
- deployment, logging destinations, or process supervision.

The Go-side `Runner` is a convenience helper outside both the wire protocol and
this Engine API contract. Engine SDKs are not required to provide an equivalent.
The existence of an engine close operation defines safe resource teardown; it
does not define the application policy that chooses when to call it.

This document defines no public client surface. Only the Go SDK implements the
separate Client API contract.

---

## 9. Conformance boundary

An engine SDK conforms only when tests can demonstrate all of the following:

- endpoint acquisition, live-owner refusal, stale cleanup, and orderly removal
  on Linux, macOS, and Windows;
- security controls are active before handshake traffic;
- exact handshake rejection, encoding selection, capability intersection, ACK,
  and session-assignment ordering;
- enforcement of `max_sessions` for `1` and a value greater than `1`;
- isolation and teardown of every item of per-session state;
- rejection of stale session handles by `session_id` and `epoch`;
- ordered connected, message/error, and disconnected events;
- uncorrelated and correlated sends on valid engine-output channels;
- explicit failures for invalid direction, absent capability, oversized data,
  invalid session, and transport failure; and
- absence of public engine process policy or a required `Runner` equivalent.

The executable acceptance criteria are defined by the
[`Engine Conformance Suite`](./ENGINE_CONFORMANCE.md). The canonical wire
behaviours and binary fixtures remain governed by
[`PROTOCOL.md`](./PROTOCOL.md) and [`test-vectors/`](./test-vectors/).
