# Yuumi Wire Protocol

Status: **alpha**

Protocol version: **`1`**

This document is the authoritative definition of the Yuumi Wire Protocol. The
keywords **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are
normative.

Yuumi is a local IPC bridge between a Go client and a logic engine. Go is the
only client role. C++, Python, Rust, and TypeScript implement the engine role.
Application lifecycle policy, restart policy, and domain semantics are outside
the protocol. All multibyte integers on the wire are unsigned and Big-Endian.

---

## 1. Protocol overview

Yuumi provides a platform-native local stream, a fixed handshake and ACK,
per-session negotiation, four logical channels, optional request/response
correlation, bounded fragmentation, and JSON Control messages.

The engine accepts one or more connections. Each accepted connection becomes an
independent session after a successful handshake, ACK, and session assignment.

---

## 2. Transport

Yuumi uses only local stream transports. TCP, IP loopback, network ports, and
any transport reachable from another host are forbidden.

| Platform | Required transport |
|---|---|
| Linux | Unix domain stream socket |
| macOS | Unix domain stream socket |
| Windows | Named Pipe in byte-stream mode |

On the same platform both endpoints **MUST** use the transport in this table.
Transport fallback between Unix domain sockets and Named Pipes is forbidden.

### 2.1 Address derivation

Address derivation takes two application-provided values:

- `endpoint_name`: 1 to 32 ASCII characters matching
  `[A-Za-z0-9][A-Za-z0-9_-]{0,31}`;
- `token`: exactly 32 lowercase hexadecimal characters encoding 128 bits
  produced by a cryptographically secure random generator.

Neither value is case-folded, Unicode-normalized, truncated, or otherwise
rewritten. An invalid value **MUST** be rejected before any endpoint is opened.
The canonical endpoint stem is:

```text
yuumi-<endpoint_name>-<token>
```

| Platform | Address |
|---|---|
| Linux / macOS | `<os_temp_dir>/<canonical_stem>.sock` |
| Windows | `\\.\pipe\<canonical_stem>` |

`<os_temp_dir>` **MUST** come from the platform temporary-directory API. SDKs
**MUST NOT** hardcode `/tmp`, `/var/tmp`, `%TEMP%`, or another directory. The
path separator is inserted exactly once. If the encoded Unix socket address is
too long for the platform socket-address structure, endpoint creation **MUST**
fail explicitly; an SDK **MUST NOT** truncate or hash it independently.

For the same platform, `endpoint_name`, `token`, and OS temporary directory, all
SDKs **MUST** produce byte-identical addresses. The token is part of the address
and access-control model. It **SHOULD** be redacted from diagnostics that do not
need the complete address.

### 2.2 Endpoint presence and stale endpoints

Endpoint presence is not evidence that an engine is alive. Liveness is tested
only by attempting a connection.

- A successful connection means the endpoint is live. A second engine
  **MUST NOT** replace it.
- A transient condition such as a busy Named Pipe **MUST NOT** be classified as
  stale while a server instance can still accept connections.
- If the connection is refused because no live listener owns the endpoint, the
  endpoint is stale and the engine **MUST** remove or release it before
  recreating it.
- On Unix, removal means unlinking the stale socket node after the refused
  connection and before binding.
- On Windows, Named Pipe objects disappear when their final server handle is
  closed. Re-creation means closing any stale handle owned by the process and
  creating a fresh server instance with the same canonical name; there is no
  filesystem node to unlink.

An engine **MUST** remove or release its endpoint during orderly shutdown.

---

## 3. Connection lifecycle

```text
Go client                               Engine
    |                                     |
    |--- Handshake (16 bytes) ----------->|
    |                                     | validate and negotiate
    |<-- ACK (4 bytes) -------------------|
    |<-- Control: session ----------------|
    |                                     |
    |<== Per-session frames =============>|
    |                                     |
    |--- Close -------------------------->|
```

The engine **MUST** send the session Control message immediately after the ACK
and before any other frame. The client **MUST** receive it before treating the
session as ready for application traffic.

Handshake rejection is signalled by closing without an ACK. A peer that has not
completed the handshake cannot receive a framed Control error.

---

## 4. Handshake

The client sends exactly 16 bytes.

```text
Offset  Size  Field
0       4     Magic
4       4     ProtocolVersion
8       4     PID
12      1     EncodingCaps
13      3     Capabilities
```

| Field | Required value or meaning |
|---|---|
| `Magic` | `0x59 0x55 0x4D 0x49` (`YUMI`) |
| `ProtocolVersion` | `0x00000001` |
| `PID` | Client process identifier as `uint32` |
| `EncodingCaps` | Encodings supported by the client |
| `Capabilities` | 24-bit client capability mask |

The engine **MUST** read exactly 16 bytes before parsing the handshake. It
**MUST** reject an invalid magic or protocol version without sending an ACK.
The handshake PID is identifying metadata, not primary authentication.

### 4.1 Encoding negotiation

| Bit | Value | Encoding |
|---|---|---|
| 0 | `0x01` | JSON |
| 1 | `0x02` | MessagePack |
| 2-7 | - | Reserved; send as zero |

The engine selects exactly one encoding from the intersection of the client
mask and the engine mask. A zero intersection is
`ERR_ENCODING_UNSUPPORTED (415)` and the engine **MUST** close without an ACK.

---

## 5. Capabilities

Capabilities negotiate additive features without changing the protocol
version. The three bytes are one Big-Endian 24-bit mask: byte 13 contains bits
23-16, byte 14 contains bits 15-8, and byte 15 contains bits 7-0.

| Bit | Mask | Name | Meaning |
|---|---|---|---|
| 0 | `0x000001` | `CAP_CORRELATION` | `FLAG_CORRELATED` frames may be used |
| 1-23 | - | Reserved | Send as zero; do not use |

The client sends its supported mask in the handshake. The engine computes:

```text
negotiated_capabilities = client_capabilities & engine_capabilities
```

The engine returns that exact intersection in ACK bytes 1-3. A capability may
be used only when its bit is set in the negotiated mask. A client **MUST** reject
an ACK that sets a capability it did not advertise. Unknown or reserved bits
received in the handshake are excluded from the intersection and otherwise
ignored.

Fragmentation, sessions, channels, and Control messages are baseline protocol
version 1 behaviour and do not have capability bits.

---

## 6. ACK

The engine sends exactly 4 bytes after a successful handshake.

```text
Offset  Size  Field
0       1     EncodingSelected
1       3     NegotiatedCapabilities
```

`EncodingSelected` is exactly one advertised value: `0x01` for JSON or `0x02`
for MessagePack. `NegotiatedCapabilities` is the Big-Endian 24-bit intersection
defined above.

An ACK with an unadvertised encoding, multiple encoding bits, or capabilities
outside the client mask is a protocol violation. The client **MUST** close.

---

## 7. Sessions

The engine accepts up to its configured `max_sessions` simultaneous
connections. `max_sessions = 1` provides one-to-one operation; a greater value
allows multiple Go clients to share one engine. The limit is engine policy and
is not negotiated on the wire.

Each connection has isolated session state:

- selected encoding and negotiated capabilities;
- heartbeat timers and counters;
- active fragment buffers;
- pending correlation identifiers;
- `session_id`;
- local connection `epoch`.

Channels are scoped to a session. The same channel number, fragment identifier,
or correlation identifier in two sessions refers to unrelated state.

### 7.1 Session assignment

After the ACK, the engine assigns an opaque identifier unique among its active
sessions and sends:

```json
{ "type": "session", "session_id": "01J4Y7M9K2P6V3N8Q5R0T1WXYZ" }
```

`session_id` is a non-empty printable ASCII string of at most 128 bytes. Clients
**MUST** treat it as opaque. Reusing an identifier while its previous session is
active is a protocol violation.

### 7.2 Reconnection

A connection established after a disconnect is a new session, not a continuation:

- the client sends a new handshake;
- encoding and capabilities are negotiated again;
- both endpoints start with empty fragment and pending-correlation state;
- the engine assigns a new `session_id`;
- the reconnecting SDK increments its local `epoch` generation counter.

`epoch` is local SDK state and is not transmitted. Its initial value is zero;
each successfully established replacement connection increments it by one. An
SDK **MUST NOT** use the old session negotiated state or buffers after close.

---

## 8. Data frames

Every frame has a 6-byte header followed by `PayloadLength` bytes.

```text
Offset  Size  Field
0       4     PayloadLength (Big-Endian uint32)
4       1     Channel
5       1     Flags
6       N     Payload
```

`PayloadLength` includes every prefix required by active flags. A receiver
**MUST** validate the declared length before allocating or reading a payload
buffer.

The maximum frame payload and maximum reassembled message data are both
16,777,216 bytes (16 MiB). Prefixes count toward the frame limit. Exceeding
either bound is `ERR_PAYLOAD_TOO_LARGE (413)`.

### 8.1 Flags

| Bit | Value | Name | Meaning |
|---|---|---|---|
| 0 | `0x01` | `FLAG_FRAGMENT` | Payload carries one fragment |
| 1 | `0x02` | `FLAG_LAST_FRAG` | Final fragment in a sequence |
| 2 | `0x04` | `FLAG_CORRELATED` | Payload carries a correlation identifier |
| 3-7 | - | Reserved | Send as zero; receipt is a protocol violation |

`FLAG_LAST_FRAG` without `FLAG_FRAGMENT` is a protocol violation. Zero denotes
one complete, uncorrelated payload.

---

## 9. Channels

| Value | Name | Direction | Purpose |
|---|---|---|---|
| `0x00` | Control | Bidirectional | Session state, heartbeat, ping/pong, protocol errors |
| `0x01` | Command | Go client to engine | Commands and requests |
| `0x02` | Log | Engine to Go client | Logs and diagnostics |
| `0x03` | Data | Bidirectional | Application data and responses |

Direction violations and unknown channels are `ERR_PROTOCOL_VIOLATION (403)`.
Channel state is never shared across sessions.

---

## 10. Request/response correlation

Correlation may be used only when `CAP_CORRELATION` was negotiated.

When `FLAG_CORRELATED` is set, a Big-Endian `uint32 correlation_id` prefixes the
message data. The requester allocates identifiers incrementally within its
session. Wrap from `0xFFFFFFFF` to `0x00000000` is allowed, but an identifier
**MUST NOT** be reused while a request with that identifier remains pending.

A response, including an application-level error response, **MUST** set
`FLAG_CORRELATED` and repeat the request `correlation_id`. Protocol-level
Control errors are connection or session errors, not application responses.

Without the flag, no correlation prefix is present and the message is
fire-and-forget. Logs, heartbeats, and uncorrelated streams retain this form.

SDK request timeouts are configurable and not negotiated. On timeout, the
pending request fails locally and its identifier is released. A late unmatched
response **MUST NOT** be delivered as the response to another request.

### 10.1 Prefix order

Prefixes appear in this fixed order:

```text
[fragment_id if FLAG_FRAGMENT]
[correlation_id if FLAG_CORRELATED]
[message or fragment data]
```

Both identifiers are Big-Endian `uint32`. When both flags are set, every
fragment repeats both prefixes, allowing each frame prefix to be decoded
without depending on a previous frame.

| Active flags | Payload layout |
|---|---|
| none | `data` |
| `FLAG_CORRELATED` | `correlation_id | data` |
| `FLAG_FRAGMENT` | `fragment_id | fragment_data` |
| both | `fragment_id | correlation_id | fragment_data` |

---

## 11. Fragmentation

The sender allocates a Big-Endian `uint32 fragment_id`. Wrap is allowed, but an
identifier **MUST NOT** be reused while its previous sequence is active in the
same session.

The receiver groups frames by session, channel, and `fragment_id`, removes the
per-frame prefixes, and concatenates fragment data in stream order. A frame with
both `FLAG_FRAGMENT` and `FLAG_LAST_FRAG` completes the message.

The following rules are normative:

- every fragment in a sequence uses the same channel and correlation state;
- if correlated, every fragment repeats the same `correlation_id`;
- a sender does not interleave two fragment sequences on the same channel;
- the receiver checks cumulative size before extending a buffer;
- an incomplete sequence is discarded after a configurable timeout, with a
  recommended default of 15 seconds;
- active sequences are capped per session, with a recommended default of 16.

A changed prefix, interleaved sequence, or exceeded active-buffer limit is
`ERR_PROTOCOL_VIOLATION (403)`. Cumulative data above 16 MiB is
`ERR_PAYLOAD_TOO_LARGE (413)`. A timed-out sequence is
`ERR_FRAGMENT_TIMEOUT (404)` and is discarded.

---

## 12. Control channel protocol

Control frames use channel `0x00` and are always JSON UTF-8, independently of
the selected application encoding. Every Control object has a string `type`.

### 12.1 Heartbeat

```json
{ "type": "heartbeat", "ts": 1784736000000 }
```

`ts` is a Unix timestamp in milliseconds UTC. Both endpoints may send
heartbeats. The interval and miss threshold are SDK-configurable and are not
wire-negotiated. Recommended defaults are 30 seconds and three missed intervals.
Any valid received frame resets the receiver liveness counter.

### 12.2 Ping and pong

```json
{ "type": "ping", "seq": 42 }
{ "type": "pong", "seq": 42 }
```

The receiver **MUST** return a pong with the same `seq` within its configured
heartbeat timeout.

### 12.3 Protocol error

```json
{ "type": "error", "code": 413, "message": "payload exceeds 16 MiB" }
```

After session establishment, an endpoint that can safely frame an error **MUST**
send this message before closing for a fatal protocol error and close
immediately afterward. The peer **MUST NOT** send more frames after receiving
it. Handshake failures close without ACK and without a Control frame.

Unknown valid Control `type` values **MUST** be ignored. This rule does not make
malformed JSON valid.

---

## 13. Status codes

Status codes are structured diagnostics used locally and in Control errors.

| Code | Name | Meaning |
|---|---|---|
| 100 | `HANDSHAKE_START` | Connection attempt initiated |
| 101 | `CONNECTING` | Transport dial in progress |
| 200 | `OK_CONNECTED` | Session established successfully |
| 201 | `OK_MESSAGE_RECEIVED` | Frame received and dispatched |
| 202 | `OK_HEARTBEAT` | Heartbeat acknowledged |
| 400 | `ERR_MAGIC_MISMATCH` | Handshake magic invalid |
| 401 | `ERR_VERSION_MISMATCH` | Protocol version incompatible |
| 402 | `ERR_PID_MISMATCH` | Optional PID check rejected the client |
| 403 | `ERR_PROTOCOL_VIOLATION` | Structurally invalid or inconsistent protocol data |
| 404 | `ERR_FRAGMENT_TIMEOUT` | Fragment sequence timed out and was discarded |
| 413 | `ERR_PAYLOAD_TOO_LARGE` | Frame or cumulative message exceeds 16 MiB |
| 415 | `ERR_ENCODING_UNSUPPORTED` | No common encoding exists |
| 500 | `ERR_PIPE_FAILED` | Local transport operation failed |
| 501 | `ERR_READ_TIMEOUT` | Read deadline exceeded |
| 502 | `ERR_WRITE_FAILED` | Transport write failed |
| 503 | `ERR_CONNECTION_LOST` | Connection closed unexpectedly |
| 599 | `ERR_INTERNAL` | Unclassified internal error |

The boundary among `403`, `413`, and `415` is strict:

- use `403` for invalid structure or state, including invalid flags, a short
  prefix, invalid channel, inconsistent fragments, invalid ACK, or malformed
  Control JSON;
- use `413` only when otherwise parseable length information exceeds the frame
  or reassembled-message bound; never allocate the oversized buffer;
- use `415` only when a syntactically valid encoding advertisement has no
  supported intersection. During handshake the engine closes without ACK.

Payload rejected by application policy is not a protocol violation and does
not use these codes.

---

## 14. Security model

The endpoint address is a capability. The 128-bit unpredictable token is part
of the address on every platform and is the primary defence against unrelated
local processes guessing it.

This does not replace OS access controls:

- on Linux and macOS, the engine **MUST** create the socket node with mode
  `0600` for the owning user;
- on Windows, the engine **MUST** apply a Named Pipe ACL restricted to the
  intended local user and **MUST** reject remote pipe clients;
- token and endpoint permissions **MUST** be in place before handshake traffic.

The PID is not authentication. An engine MAY configure `expected_pid` as an
additional check. A mismatch closes without ACK and surfaces
`ERR_PID_MISMATCH (402)`. If the OS exposes trustworthy peer credentials, the
engine SHOULD compare them with the handshake PID. Multiple sessions do not
share one mandatory expected PID.

---

## 15. Versioning

Yuumi has three independent version scales.

| Scale | Purpose | Evolution rule |
|---|---|---|
| Protocol version | Compatibility gate in the 4-byte handshake field | Plain integer; increases only for an incompatible wire break |
| Capabilities | Negotiation of additive wire features | One assigned bit per feature; enabled by endpoint intersection |
| Library version | Release identifier for one SDK | Independent semantic version per repository |

The current protocol version is `1`. It is not semantic versioning and has no
alpha, beta, release-candidate, or final value on the wire. The specification
itself is currently alpha. Library versions are visible metadata and
**MUST NOT** be used to accept or reject a connection.

Protocol revisions are recorded in `CHANGELOG.md` as dated, git-style entries
describing what changed and why. Additive features use capabilities; they do not
increment the protocol version.

---

## 16. Governance and conformance

`yuumi-spec` is the source of truth. Wire changes originate here and flow to
SDKs. A public SDK API must belong to either the Go Client API contract or the
Engine API contract; those contracts are intentionally different.

Conformance is established by executing canonical vectors in
[`test-vectors/`](./test-vectors/), not by code inspection. Every `.bin` file
has a same-basename `.json` annotation containing its exact hexadecimal bytes,
field offsets, context, and expected outcome.

### Canonical test vectors

| Binary vector | Purpose |
|---|---|
| `handshake_valid.bin` | Valid version 1 handshake without additive capabilities |
| `handshake_bad_magic.bin` | Invalid magic rejection with `400` and no ACK |
| `handshake_bad_version.bin` | Incompatible version rejection with `401` and no ACK |
| `handshake_cap_correlation.bin` | Client advertisement of `CAP_CORRELATION` |
| `handshake_encoding_unsupported.bin` | Empty encoding intersection rejection with `415` and no ACK |
| `ack_json.bin` | JSON selection with no negotiated capabilities |
| `ack_msgpack.bin` | MessagePack selection with no negotiated capabilities |
| `ack_cap_correlation.bin` | Correlation capability present in both endpoint masks |
| `ack_capabilities_none.bin` | Correlation advertised only by the client and excluded by intersection |
| `ack_unadvertised_capability.bin` | Invalid ACK capability rejection with `403` |
| `frame_channel_command.bin` | Complete fire-and-forget command |
| `frame_oversized.bin` | Declared payload above 16 MiB rejected with `413` before allocation |
| `frame_fragment_first.bin` | First uncorrelated fragment |
| `frame_fragment_last.bin` | Final uncorrelated fragment and completed reassembly |
| `frame_correlated_request.bin` | Correlated request with identifier 42 |
| `frame_correlated_response.bin` | Response repeating identifier 42 |
| `frame_correlated_not_negotiated.bin` | Correlation used without capability negotiation, rejected with `403` |
| `frame_fragment_correlated_first.bin` | First fragment with `fragment_id` before `correlation_id` |
| `frame_fragment_correlated_last.bin` | Final fragment repeating both identifiers in prefix order |
| `control_session.bin` | Engine session assignment immediately after ACK |
| `control_session_empty_id.bin` | Empty session identifier rejection with `403` |
| `control_heartbeat.bin` | JSON heartbeat |
| `control_ping.bin` | JSON ping with sequence 1 |
| `control_pong.bin` | JSON pong echoing sequence 1 |
| `control_error.bin` | JSON payload-size error with status `413` |

### Conformance checklist

A conforming implementation must:

- [ ] use Unix domain stream sockets on Linux/macOS and Named Pipes on Windows;
- [ ] never use TCP and use the required transport at both endpoints;
- [ ] derive a byte-identical address from name, token, and the OS temp API;
- [ ] enforce `0600` on Unix or the required Named Pipe ACL on Windows;
- [ ] test endpoint liveness by connecting and remove or release stale endpoints;
- [ ] send and parse the 16-byte handshake with protocol version `1`;
- [ ] negotiate one encoding and reject an empty intersection with `415`;
- [ ] negotiate capabilities by intersection and return them in the 4-byte ACK;
- [ ] accept up to the configured number of isolated sessions;
- [ ] send and validate session assignment immediately after the ACK;
- [ ] reset negotiated state, buffers, and identifiers on reconnection;
- [ ] keep channels, fragments, correlations, and heartbeat isolated per session;
- [ ] validate lengths before allocation and enforce both 16 MiB bounds;
- [ ] parse prefixes in fragment-then-correlation order;
- [ ] repeat and validate both identifiers on every correlated fragment;
- [ ] correlate responses and application errors with the request identifier;
- [ ] preserve fire-and-forget behaviour without the correlation flag;
- [ ] discard incomplete fragments on timeout and enforce the buffer limit;
- [ ] encode Control as JSON and ignore unknown valid Control types;
- [ ] distinguish structural `403`, size `413`, and encoding `415` failures;
- [ ] treat `expected_pid` only as an optional additional control.
