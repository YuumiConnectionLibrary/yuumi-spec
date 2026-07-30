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

Go opens and owns the listener. An engine connects as a dialer and is only a
candidate until the handshake, ACK, and session assignment complete
successfully. The listener permits exactly one established engine session at a
time.

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
rewritten. Both values **MUST** be validated before any transport address is
derived or used.

On Windows, the canonical address is:

```text
\\.\pipe\yuumi-<endpoint_name>-<token>
```

On Linux and macOS, the canonical filename is:

```text
yuumi-<digest>.sock
```

`digest` is the first 32 lowercase hexadecimal characters of:

```text
SHA-256(UTF-8("yuumi") || 0x00 || UTF-8(endpoint_name) || 0x00 || UTF-8(token))
```

Each `0x00` is exactly one zero byte. The hexadecimal digest is computed from
the 32-byte SHA-256 result in its normal byte order, using two lowercase
characters per byte, and is then truncated to its first 32 characters. The
token therefore participates in Unix address derivation without appearing in
clear text in the pathname.

`<os_temp_dir>` **MUST** come from the platform temporary-directory API. SDKs
**MUST NOT** hardcode `/tmp`, `/var/tmp`, `%TEMP%`, or another directory. To
compose the Unix address, remove every trailing `/` byte from `<os_temp_dir>`,
then concatenate one `/` byte and `yuumi-<digest>.sock`. This also maps the root
directory `/` to `/yuumi-<digest>.sock` and guarantees exactly one separator.

The complete Unix pathname **MUST** be encoded with the platform filesystem
encoding and validated in bytes, not characters, before `listen` or `dial`.
On macOS, the encoded pathname plus its terminating NUL **MUST** fit the
104-byte `sun_path` field, so the encoded pathname is at most 103 bytes. An
address too long for the platform socket-address structure **MUST** fail as a
configuration error; an SDK **MUST NOT** truncate, relocate, or apply another
hash.

For the same platform, `endpoint_name`, `token`, and OS temporary directory, all
five SDKs **MUST** produce byte-identical addresses. The token is part of the
address and access-control model. It **SHOULD** be redacted from diagnostics
that do not need the complete address.

#### 2.1.1 Canonical address examples

The following examples are reproducible. Byte counts are UTF-8 byte counts;
all characters shown are ASCII. Their deterministic tokens are fixtures for
address conformance and **MUST NOT** be reused as production access tokens.

| Case | `endpoint_name` | `token` | SHA-256 prefix (`digest`) |
|---|---|---|---|
| Minimum name | `a` | `000102030405060708090a0b0c0d0e0f` | `c3da2f7decb02b7a24e054711453a85c` |
| Maximum 32-byte name | `ABCDEFGHIJKLMNOPQRSTUVWXYZ012345` | `f0e0d0c0b0a090807060504030201000` | `a9ce40da7198349aab024f107b698ef4` |

For the minimum-name case:

```text
Windows:
\\.\pipe\yuumi-a-000102030405060708090a0b0c0d0e0f

Unix filename:
yuumi-c3da2f7decb02b7a24e054711453a85c.sock

Unix address when os_temp_dir is /tmp:
/tmp/yuumi-c3da2f7decb02b7a24e054711453a85c.sock
```

For the maximum-name case:

```text
Windows:
\\.\pipe\yuumi-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345-f0e0d0c0b0a090807060504030201000

Unix filename:
yuumi-a9ce40da7198349aab024f107b698ef4.sock
```

The compact Unix filename is always 43 bytes: 6 bytes for `yuumi-`, 32 for the
digest, and 5 for `.sock`. The macOS worst-case budget is therefore:

```text
59-byte os_temp_dir + 1-byte separator + 43-byte filename = 103 bytes
```

Using the minimum-name digest, this 59-byte temporary directory is the longest
accepted example:

```text
/private/var/folders/aa/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/T
```

It produces this exactly 103-byte pathname:

```text
/private/var/folders/aa/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/T/yuumi-c3da2f7decb02b7a24e054711453a85c.sock
```

Adding one `b` makes the directory 60 bytes and the complete pathname 104
bytes. Go **MUST** fail before opening the listener, and every engine **MUST**
fail before dialing; the terminating NUL would otherwise require byte 105 of
the 104-byte `sun_path` field.

### 2.2 Endpoint presence and stale endpoints

Endpoint presence is not evidence that a Go listener is alive. Liveness is
tested only by attempting a connection.

- A successful connection means the endpoint is live. A second Go listener
  **MUST NOT** replace it.
- A transient condition such as a busy Named Pipe **MUST NOT** be classified as
  stale while a listener instance can still accept connections.
- If the connection is refused because no live listener owns the endpoint, the
  endpoint is stale and Go **MUST** remove or release it before recreating it.
- On Unix, removal means unlinking the stale socket node after the refused
  connection and before binding.
- On Windows, Named Pipe objects disappear when their final listener handle is
  closed. Re-creation means Go closes any stale handle it owns and creates a
  fresh listener with the same canonical name; there is no filesystem node to
  unlink.

Go **MUST** remove or release its endpoint during orderly listener shutdown.

---

## 3. Connection lifecycle

```text
Go client and listener                  Engine dialer
    |                                     |
    | [open and protect endpoint]          |
    |<-- Connect --------------------------|
    | [accept candidate]                   |
    |--- Handshake (16 bytes) ----------->|
    |                                     | validate and negotiate
    |<-- ACK (4 bytes) -------------------|
    |<-- Control: session ----------------|
    | [session established]                |
    |<== Per-session frames =============>|
    |                                     |
    |--- Close -------------------------->|
```

Go **MUST** send the handshake after accepting the engine candidate. Listener
ownership does not reverse the handshake direction.

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

Each Go listener permits exactly one established engine session at a time. This
one-to-one limit is mandatory and is not configurable or negotiated on the
wire. Go **MUST** accept and evaluate one engine candidate at a time, and only
while no session is established. A candidate becomes the established session
only after its handshake, ACK, and session assignment succeed. If a candidate
fails transport authentication, disconnects, returns an invalid ACK, or sends
an invalid session assignment, Go **MUST** close it and continue accepting
candidates; rejection does not consume the session slot.

The established connection has isolated session state:

- selected encoding and negotiated capabilities;
- heartbeat timers and counters;
- active fragment buffers;
- pending correlation identifiers;
- `session_id`;
- local connection `epoch`.

Channels are scoped to a session. The same channel number, fragment identifier,
or correlation identifier in two sequential sessions refers to unrelated
state.

### 7.1 Session assignment

After the ACK, the engine assigns an opaque identifier to the new session and
sends:

```json
{ "type": "session", "session_id": "01J4Y7M9K2P6V3N8Q5R0T1WXYZ" }
```

`session_id` is a non-empty printable ASCII string of at most 128 bytes. Clients
**MUST** treat it as opaque.

### 7.2 Reconnection

A connection established after a disconnect is a new session, not a continuation:

- the client sends a new handshake;
- encoding and capabilities are negotiated again;
- both endpoints start with empty fragment and pending-correlation state;
- the engine assigns a new `session_id`;
- both endpoints replace their local `epoch` generation.

`epoch` is opaque local SDK state and is not transmitted. Each endpoint
**MUST** replace it for every successfully established session. A request,
responder, timeout, callback, or send operation created in an earlier epoch
**MUST NOT** act on a later connection. An SDK **MUST NOT** use old negotiated
state or buffers after close.

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
| 402 | `ERR_PID_MISMATCH` | Optional PID check rejected a peer |
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
  prefix, invalid channel, inconsistent fragments, invalid ACK, malformed
  Control JSON, or an application payload that cannot be decoded with the
  session's negotiated encoding after successful reassembly;
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

- on Linux and macOS, Go **MUST** create the socket node with mode `0600` for
  the owning user;
- on Windows, Go **MUST** apply a Named Pipe ACL restricted to the intended
  local user and **MUST** reject remote pipe clients;
- Go **MUST** put the token and endpoint permissions in place before accepting
  traffic.

The handshake PID identifies the Go process and is not authentication. If the
OS exposes trustworthy server credentials, the engine **SHOULD** compare them
with the handshake PID. An engine mismatch closes without ACK and surfaces
`ERR_PID_MISMATCH (402)`.

Go **MAY** configure an expected engine PID as an additional candidate check
when the OS exposes trustworthy client credentials. A mismatch closes the
candidate before handshake, surfaces `ERR_PID_MISMATCH (402)` locally, and
**MUST NOT** consume the session slot.

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
[`Engine API contract`](./ENGINE_API.md); those contracts are intentionally
different.

Conformance is established by executing canonical vectors in
[`test-vectors/`](./test-vectors/), not by code inspection. Every `.bin` file
has a same-basename `.json` annotation containing its exact hexadecimal bytes,
field offsets, context, and expected outcome.

The Go client uses the numbered
[`Client Conformance Suite`](./CLIENT_CONFORMANCE.md). The C++, Python, Rust,
and TypeScript engines use the numbered
[`Engine Conformance Suite`](./ENGINE_CONFORMANCE.md). Those suites are the
role-specific acceptance criteria for all five SDKs.

### Canonical test vectors

Task 01 changed transport ownership and address derivation only. Task 02
confirmed every existing version 1 handshake, ACK, Control, and data-frame
vector byte-for-byte unchanged. Address derivation is covered separately by a
machine-readable fixture; it does not introduce a wire packet.

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

### Canonical non-wire fixtures

| Fixture | Purpose |
|---|---|
| `address_derivation.json` | Minimum and maximum input, changed name/token, macOS 103/104-byte boundaries, and invalid configuration cases |
| `manifest.json` | Size, SHA-256, classification, purpose, and annotation hash for every canonical fixture |

`tools/vector_tool.py` deterministically generates the non-wire fixtures and
validates that every `.bin` is exactly equal to its companion `packet.hex`.
The default check also pins protocol version `1`, verifies every manifest hash,
and rejects orphaned or missing annotations. Run:

```text
python tools/vector_tool.py
```

### Conformance checklist

A conforming implementation must:

- [ ] use Unix domain stream sockets on Linux/macOS and Named Pipes on Windows;
- [ ] never use TCP and use the required transport at both endpoints;
- [ ] validate name and token before transport use;
- [ ] derive a byte-identical address from name, token, and the OS temp API,
  including the two NUL bytes and lowercase SHA-256 prefix on Unix;
- [ ] reject a macOS Unix pathname longer than 103 encoded bytes;
- [ ] have Go open and own the listener and the engine connect as a dialer;
- [ ] have Go enforce `0600` or the required Named Pipe ACL before accepting
  traffic;
- [ ] have Go test endpoint liveness and remove or release stale endpoints;
- [ ] have Go send the 16-byte handshake after accepting an engine candidate;
- [ ] parse the handshake with protocol version `1`;
- [ ] negotiate one encoding and reject an empty intersection with `415`;
- [ ] negotiate capabilities by intersection and return them in the 4-byte ACK;
- [ ] establish exactly one engine session at a time;
- [ ] reject an invalid candidate without consuming the session slot;
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
