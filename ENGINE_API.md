# Yuumi Engine API Contract

Status: **alpha**

Wire protocol: **version `1`**

This document is the authoritative, language-neutral contract for Yuumi engine
SDKs. C++, Python, Rust, and TypeScript implement this role. The keywords
**MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are normative.

The Engine API is intentionally different from the Go Client API. An engine
derives the canonical address, connects to the Go-owned listener as a dialer,
receives the unchanged client handshake, and returns the unchanged ACK and
session assignment. A listener, endpoint owner, or public non-Go client does
not satisfy this contract.

Names describe operations and values, not mandatory language spellings. Each
SDK **MUST** expose the same observable behaviour through idiomatic constructs.

---

## 1. Engine configuration

An engine instance **MUST** accept this configuration before dialing:

| Option | Contract |
|---|---|
| `endpoint_name` | Required. It **MUST** satisfy `PROTOCOL.md`. |
| `token` | Required. Exactly 32 lowercase hexadecimal characters; it participates in canonical address derivation. |
| `supported_encodings` | Optional ordered preference, default MessagePack then JSON. At least one distinct version 1 encoding is required. |
| `supported_capabilities` | Optional bitmask, default `CAP_CORRELATION`. A conforming version 1 engine **MUST** implement `CAP_CORRELATION` and never enable an unimplemented or reserved bit. |
| `expected_pid` | Optional expected Go PID. Absence disables this additional check; zero is a value, not a sentinel. |
| heartbeat settings | Optional positive interval and miss limit. Protocol recommendations are defaults when enabled. |
| fragmentation settings | Optional positive timeout and active-sequence limit. The 16 MiB wire bounds remain mandatory. |

Invalid configuration **MUST** fail before any transport operation. There is
no `max_sessions`: one engine instance has at most one established connection.
Retry, reconnect timing, and process lifecycle are application policy and are
not hidden configuration.

---

## 2. Required Engine API surface

A conforming SDK **MUST** provide these operations or language-native
equivalents:

| Operation | Required behaviour |
|---|---|
| Connect engine | Validate configuration, derive the address, dial the Go listener, receive and validate the handshake, send ACK and session assignment, then start dispatch. Success means one session is established. |
| Close engine | Stop session work, close the connection, finish disconnect notification, and release all resources. Repeated close is safe. |
| Send message | Accept an engine-to-client application channel and payload and send an uncorrelated message using current negotiated state. |
| Send correlated message | Accept an engine-to-client channel, `uint32` correlation ID, and payload; require negotiated `CAP_CORRELATION`. |
| Register or consume events | Deliver connected, message, error, and disconnected events with the ordering below. |
| Inspect session state | Expose immutable `session_id`, local epoch, selected encoding, and negotiated capabilities while connected. |

Control traffic belongs to the SDK. Applications cannot forge session
assignment, heartbeat, ping/pong, or protocol errors, and cannot send on a
channel forbidden to the engine.

Sequential accepted sends preserve transport order. A send fails explicitly
when no session exists, the captured epoch is stale, direction is invalid,
correlation was not negotiated, serialization fails, or a size limit would be
exceeded. If acceptance means queued, a later write failure **MUST** surface as
an error event and never as success.

---

## 3. Address derivation and transport connection

Before dialing, the engine **MUST**:

1. validate all configuration, `endpoint_name`, and token;
2. derive exactly the Windows pipe name or Unix SHA-256 filename in
   `PROTOCOL.md`;
3. validate a Unix pathname in encoded bytes, including the 103-byte macOS
   limit; and
4. dial a Unix domain stream socket on Linux/macOS or a byte-stream Named Pipe
   on Windows.

The engine **MUST NOT** create, bind, protect, probe for stale ownership,
unlink, replace, or remove an endpoint. Those responsibilities belong only to
Go. It **MUST NOT** use TCP or another fallback.

A refused or absent endpoint causes the connect attempt to fail explicitly.
The SDK does not silently retry or wait for process lifecycle. A busy Windows
pipe is a live-listener condition, not a stale endpoint that the engine may
replace. Token values should be redacted from routine diagnostics.

---

## 4. Engine-side handshake

After the transport connects, the engine remains a candidate until every step
succeeds:

1. read exactly 16 handshake bytes before parsing;
2. validate magic and protocol version `1`;
3. when `expected_pid` is present, compare it with the handshake PID and, where
   trustworthy server credentials exist, verify those credentials;
4. select the first configured encoding in the client mask;
5. compute `client_capabilities & supported_capabilities`, excluding unknown
   and reserved bits;
6. send the exact 4-byte ACK;
7. allocate a new printable opaque `session_id` and local epoch;
8. send Control session assignment immediately after ACK and before any other
   frame; and
9. mark the session established, start dispatch, and emit connected.

Invalid magic, incompatible version, empty encoding intersection, or PID
mismatch closes without ACK. A short handshake or pre-ACK transport failure
also closes without ACK. An ACK or session-assignment write failure never emits
connected or disconnected because no session was established. Each failure is
observable with its applicable status and phase.

The engine never sends a framed Control error to a candidate. Listener
inversion changes none of the handshake, ACK, Control, or frame bytes and does
not change their Go-to-engine / engine-to-Go direction.

---

## 5. Session and opaque epoch

Every successful `Connect` creates one isolated session with:

| State | Invariant |
|---|---|
| selected encoding | Exactly the ACK selection; immutable. |
| negotiated capabilities | Exactly the ACK intersection; immutable. |
| heartbeat state | Timers and counters belong only to this connection. |
| fragmentation state | Buffers, identifiers, sizes, and deadlines never survive disconnect. |
| correlation state | Pending identifiers never survive disconnect. |
| `session_id` | New non-empty printable ASCII, at most 128 bytes, sent in session assignment. |
| `epoch` | Opaque local generation, replaced for every established session and never transmitted. |

An engine instance cannot connect again until the prior session has completely
torn down. A later `Connect` is a new session, performs the complete handshake,
uses a new `session_id`, replaces the epoch, and starts with empty state. There
is no resumption.

A message callback, responder, queued send, timeout, fragment, or correlation
captures the session epoch. Work from a previous epoch fails or is discarded
and cannot write to, emit against, or close the replacement.

---

## 6. Event contract

One session preserves this order:

```text
connected
zero or more message/error events
disconnected
```

Application events **MUST** be delivered serially for that session. The SDK
documents its execution context. A slow handler **MUST NOT** block transport
reads/writes, heartbeat, timeouts, or close.

The connected event fires once after ACK and session assignment are both
written. It exposes immutable session ID, epoch, encoding, and capabilities.
Rejected candidates produce no connected or disconnected event.

The message event fires once per complete valid decoded non-Control message and
includes channel, decoded payload, optional correlation ID, and a responder or
equivalent operation bound to the captured epoch. Fragments are delivered only
after complete reassembly. Invalid, partial, Control, and wrong-direction input
never reaches the application.

Error events preserve category, status when applicable, phase, cause, and the
current epoch when a session exists. A terminal cause is reported once and is
never replaced by empty data or a normal result. After establishment, a safely
frameable fatal protocol error sends Control error then closes.

Disconnected fires exactly once for each connected event and distinguishes
local close, Go close, heartbeat timeout, protocol failure, and transport
failure. No application callback for that epoch may begin afterward.

---

## 7. Security contract

The engine validates the token before dialing and derives the address with that
exact token. The public API **MUST NOT** accept an arbitrary full path that
bypasses canonical derivation.

The token and Go-owned endpoint ACL or `0600` mode are the baseline. The
handshake PID identifies the Go process but is not authentication. When the OS
exposes trustworthy server credentials, the engine **SHOULD** compare them with
the handshake PID. Configured `expected_pid` is an optional additional check;
a mismatch reports `ERR_PID_MISMATCH (402)` and closes without ACK.

Engine SDKs do not weaken Go endpoint security, request remote pipe access, or
add network fallback. Python uses its required `ctypes` Named Pipe dial shim and
has no native install step; TypeScript uses standard Node dial APIs.

---

## 8. What the Engine API does not cover

This contract does not decide who launches, stops, supervises, discovers, or
restarts either process. It does not capture stdout/stderr, find executables,
define application schemas or routing, prescribe packaging, or require an
engine `Runner`. An optional environment adapter may only read explicit
configuration and invoke the fundamental connect operation.

This document defines no listener surface and no public client surface. Only
the Go SDK implements the separate Client API and owns the endpoint.

---

## 9. Conformance boundary

An engine SDK conforms only when the
[`Engine Conformance Suite`](./ENGINE_CONFORMANCE.md) demonstrates canonical
address derivation, dial-only transport, received version 1 handshake, exact
ACK/session ordering, unchanged frame behaviour, stale-epoch rejection, and
absence of listener or application-lifecycle policy on all three platforms.
