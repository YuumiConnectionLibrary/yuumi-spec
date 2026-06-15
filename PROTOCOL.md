# Yuumi Wire Protocol — Specification v2.final

This document is the authoritative definition of the Yuumi IPC wire protocol.
All language implementations (Go, C++, Rust, Python, …) must conform to this spec.

> **Stability guarantee:** Protocol v2 is frozen. No breaking changes will be
> introduced for 12 months from the v2.final release date (2026-06-02).
> New features will be additive only.

---

## Overview

Yuumi is a binary IPC protocol over Unix domain sockets (`.sock` files).
It provides:

- **Handshake** — magic, version, and PID verification with encoding negotiation
- **Multiplexed channels** — 4 logical channels over a single connection
- **Dual encoding** — JSON or MessagePack, negotiated at handshake
- **Frame safety** — 16 MiB maximum payload to prevent OOM
- **Fragmentation** — large payloads split across multiple frames via Flags byte
- **Control channel protocol** — structured heartbeat, ping/pong, and error messages

---

## Transport

| Platform | Mechanism |
|---|---|
| Linux / macOS | Unix domain socket (`AF_UNIX`) |
| Windows | Unix domain socket via WSL2 / Windows AF_UNIX (Win10 1803+) |

Socket path:

```
<os_temp_dir>/<normalized_pipe_name>.sock
```

`normalized_pipe_name` is truncated to **64 bytes** (UTF-8) before appending `.sock`.

Use platform APIs for temp dir:
- Go: `os.TempDir()`
- C++: `std::filesystem::temp_directory_path()`

Never hardcode `/tmp` or `%TEMP%`.

---

## Connection Lifecycle

```
Client                          Server
  │                               │
  │── Handshake (16 bytes) ──────▶│
  │                               │  validate magic, version, PID
  │◀─── ACK (4 bytes) ────────────│  select encoding
  │                               │
  │══ Data frames (bidirectional) ═│
  │   (ChannelControl: heartbeat,  │
  │    ping/pong, error — JSON)    │
  │                               │
  │── Close ──────────────────────▶│
```

---

## Handshake Packet (Client → Server)

**Size: 16 bytes, all fields Big-Endian.**

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
├───────────────────────────────────────────────────────────────────┤
│                    Magic  (4 bytes)  0x59554D49                   │
├───────────────────────────────────────────────────────────────────┤
│                    Version (4 bytes) uint32                       │
├───────────────────────────────────────────────────────────────────┤
│                    PID     (4 bytes) uint32                       │
├───────────────┬───────────────────────────────────────────────────┤
│ EncodingCaps  │              Reserved (3 bytes, must be 0x00)     │
│   (1 byte)    │                                                   │
└───────────────┴───────────────────────────────────────────────────┘
```

| Field | Offset | Size | Description |
|---|---|---|---|
| Magic | 0 | 4 B | `0x59 0x55 0x4D 0x49` ("YUMI" in ASCII) |
| Version | 4 | 4 B | Protocol version, currently `2` |
| PID | 8 | 4 B | Client process ID |
| EncodingCaps | 12 | 1 B | Bitmask of supported encodings |
| Reserved | 13 | 3 B | Must be `0x00 0x00 0x00` |

**EncodingCaps bitmask:**

| Bit | Value | Encoding |
|---|---|---|
| 0 | `0x01` | JSON |
| 1 | `0x02` | MessagePack |

A client that supports both sends `0x03`.

---

## ACK Packet (Server → Client)

**Size: 4 bytes.**

```
┌───────────────┬───────────────────────────────────────────────────┐
│ EncodingSelected│          Reserved (3 bytes, 0x00)              │
│   (1 byte)    │                                                   │
└───────────────┴───────────────────────────────────────────────────┘
```

The server selects **one** encoding from the client's capabilities bitmask and places it in byte 0.

**Rejection:** If magic, version, or PID validation fails, the server **closes the connection without sending an ACK**. The client must treat an EOF or read error at this stage as a handshake failure.

---

## Data Frame

**Header: 6 bytes (Big-Endian), followed by the payload.**

```
 0       1       2       3       4       5       6 … 6+N-1
├───────┴───────┴───────┴───────┼───────┼───────┼──────────────────┤
│       Payload Length (BE u32) │Channel│ Flags │  Payload (N B)   │
└───────────────────────────────┴───────┴───────┴──────────────────┘
```

| Field | Offset | Size | Description |
|---|---|---|---|
| Payload Length | 0 | 4 B | Length of payload in bytes (Big-Endian uint32) |
| Channel | 4 | 1 B | Logical channel identifier |
| Flags | 5 | 1 B | Fragmentation flags bitmask (see Fragmentation) |
| Payload | 6 | N B | Serialized message body |

**Flags bitmask:**

| Bit | Value | Name | Meaning |
|---|---|---|---|
| 0 | `0x01` | `FLAG_FRAGMENT` | This frame carries a fragment of a larger payload |
| 1 | `0x02` | `FLAG_LAST_FRAG` | This is the last fragment of the sequence |
| 2–7 | — | Reserved | Must be `0x00` |

A frame with `Flags = 0x00` is a complete, unfragmented payload (standard behavior).

**Maximum payload size: 16,777,216 bytes (16 MiB).** Frames exceeding this must be rejected with `ERR_PROTOCOL_VIOLATION (403)`.

---

## Fragmentation

Fragmentation allows payloads larger than the practical single-frame limit to be
split across multiple frames on the same channel. It reuses the `Flags` byte of
the existing frame header — no change to the wire format.

### Fragment frame layout

When `FLAG_FRAGMENT (0x01)` is set, the **first 4 bytes of the payload field**
are a `fragment_id` (uint32, Big-Endian). The remaining bytes are the fragment data.

```
 6       7       8       9      10 … 6+N-1
├───────┴───────┴───────┴───────┼──────────────────┤
│       fragment_id (BE u32)    │  fragment data   │
└───────────────────────────────┴──────────────────┘
```

The `Payload Length` field in the frame header includes the 4-byte `fragment_id`
prefix — i.e. `payload_length = 4 + len(fragment_data)`.

### Reassembly rules

A receiver accumulates fragments by `fragment_id` and reconstructs the original
payload when `FLAG_LAST_FRAG (0x02)` is also set.

| Rule | Detail |
|---|---|
| **Order** | Fragments arrive in order (Unix socket guarantees stream ordering). No explicit sequence number is needed. |
| **Completion** | `FLAG_FRAGMENT \| FLAG_LAST_FRAG` (`0x03`) marks the final fragment. The receiver concatenates all fragment data (excluding the `fragment_id` prefix) and dispatches the full payload. |
| **Timeout** | If `FLAG_LAST_FRAG` is not received within **T seconds** of the last fragment for a given `fragment_id`, the buffer is discarded and an internal timeout error is raised (`ERR_FRAGMENT_TIMEOUT`, 404). T is SDK-configurable; the recommended default is **15 seconds**. |
| **Concurrent cap** | The maximum number of simultaneously active `fragment_id` values per connection is SDK-configurable; the recommended default is **16**. Exceeding the cap closes the connection with `ERR_PROTOCOL_VIOLATION (403)`. |
| **ID wrap** | `fragment_id` is uint32 and may wrap. Receivers handle wrap incrementally (next ID after `0xFFFFFFFF` is `0x00000000`). |
| **Non-fragmented frames** | `Flags = 0x00` frames are always complete payloads. A receiver must never attempt reassembly unless `FLAG_FRAGMENT` is set. |

### Sender rules

- A sender **must not** mix `fragment_id` values interleaved on the same channel
  without completing or timing out the previous sequence.
- All fragments of a sequence **must** be sent on the same `Channel`.
- The `Payload Length` of each fragment frame **must** be ≤ 16 MiB (the standard
  frame cap applies per-fragment, not per-reassembled payload).

---

## Channels

| Value | Name | Direction | Purpose |
|---|---|---|---|
| `0x00` | Control | Bidirectional | Heartbeat, ping/pong, lifecycle errors (see Control Channel Protocol) |
| `0x01` | Command | Host → Sidecar | Commands, requests |
| `0x02` | Log | Sidecar → Host | Log output, diagnostics |
| `0x03` | Data | Bidirectional | Payload data exchange |

---

## Control Channel Protocol

`ChannelControl` (`0x00`) carries structured lifecycle messages between the two
endpoints. These messages are **always encoded as JSON**, regardless of the
encoding negotiated during handshake.

> **Rationale:** Control messages are low-frequency and human-readable by design.
> Using a fixed encoding eliminates ambiguity across implementations.

### Message schema

All Control messages share the field `"type"` as a discriminator.

#### Heartbeat

Sent periodically by both endpoints to signal liveness.

```json
{ "type": "heartbeat", "ts": 1748558400000 }
```

| Field | Type | Description |
|---|---|---|
| `type` | string | `"heartbeat"` |
| `ts` | integer | Unix timestamp in **milliseconds** (UTC) |

#### Ping / Pong

Used for latency measurement. The receiver must reply with a `pong` carrying the
same `seq` value **within the configured heartbeat timeout window**.

```json
{ "type": "ping", "seq": 42 }
{ "type": "pong", "seq": 42 }
```

| Field | Type | Description |
|---|---|---|
| `type` | string | `"ping"` or `"pong"` |
| `seq` | integer | Sequence number, echoed in the `pong` |

#### Error

Sent by either endpoint to signal a protocol-level error before closing the
connection. The sender **must** close the connection immediately after sending
this message; the receiver **must not** send further data frames after receiving it.

```json
{ "type": "error", "code": 403, "message": "payload too large" }
```

| Field | Type | Description |
|---|---|---|
| `type` | string | `"error"` |
| `code` | integer | Status code (see Status Codes) |
| `message` | string | Human-readable description |

### Heartbeat configuration

The heartbeat interval and miss threshold are **SDK-configurable**; they are not
negotiated on the wire. Both endpoints operate independently with their own settings.

| Parameter | Recommended default | Description |
|---|---|---|
| `interval` | 30 s | Time between outgoing heartbeat messages |
| `miss_threshold` | 3 | Consecutive missed heartbeats before declaring the connection lost |
| `enabled` | `true` | Set to `false` to disable heartbeat entirely (e.g. in tests) |

A missed heartbeat is defined as: no message of any kind received from the remote
endpoint within `interval` seconds. Any received frame (data or control) resets the
miss counter.

### Forward compatibility

A receiver that encounters a `"type"` value it does not recognise **must silently
ignore** the message and continue. This allows future Control message types to be
added without breaking existing implementations.

---

## Security Model

### Socket permissions

The server **must** create the Unix socket with mode `0600` (owner read/write only).
If a platform/runtime does not support permission enforcement for the socket node,
this guarantee degrades and must be treated as best-effort.

### PID strict mode

Servers may enforce a configured `expected_pid`:

- If `expected_pid != 0`: the server rejects a handshake with a different PID by
  closing the connection **without ACK** and surfacing `ERR_PID_MISMATCH (402)`.
- If `expected_pid == 0`: any client PID is accepted.

### Platform credentials and trust model

| Platform | Credential source | PID handling |
|---|---|---|
| Linux | `SO_PEERCRED` → `struct ucred { pid, uid, gid }` | PID is verifiable from peer credentials |
| macOS | `LOCAL_PEERCRED` → `struct xucred { uid, gid }` | No PID in credential struct; fallback validation uses `proc_pidpath` to confirm PID exists and executable path matches expected binary |
| Windows | Filesystem ACLs on AF_UNIX socket path | Handshake PID is accepted as-is when ACL ownership/permissions are trusted |

---

## Status Codes

Status codes identify protocol events in structured error types. They are **not transmitted on the wire** — they are internal diagnostics. The `code` field in a Control `error` message uses the same values.

| Code | Name | Meaning |
|---|---|---|
| 100 | HANDSHAKE_START | Connection attempt initiated |
| 101 | CONNECTING | Transport dial in progress |
| 200 | OK_CONNECTED | Handshake completed successfully |
| 201 | OK_MESSAGE_RECEIVED | Frame received and dispatched |
| 202 | OK_HEARTBEAT | Heartbeat acknowledged |
| 400 | ERR_MAGIC_MISMATCH | Handshake magic invalid |
| 401 | ERR_VERSION_MISMATCH | Protocol version incompatible |
| 402 | ERR_PID_MISMATCH | Client PID rejected |
| 403 | ERR_PROTOCOL_VIOLATION | Invalid framing, payload too large, or fragmentation cap exceeded |
| 404 | ERR_FRAGMENT_TIMEOUT | Fragment reassembly timed out — sequence discarded |
| 500 | ERR_PIPE_FAILED | Transport connection failed |
| 501 | ERR_READ_TIMEOUT | Read deadline exceeded |
| 502 | ERR_WRITE_FAILED | Write to transport failed |
| 503 | ERR_CONNECTION_LOST | Unexpected connection close |
| 599 | ERR_INTERNAL | Unclassified internal error |

---

## Test Vectors

Canonical binary test vectors are in [`test-vectors/`](./test-vectors/). Each file has a companion `.json` with field-by-field annotations.

| File | Description |
|---|---|
| `handshake_valid.bin` | Valid handshake, version=2, JSON+MsgPack caps |
| `handshake_bad_magic.bin` | Magic = `0xDEADBEEF` (should be rejected) |
| `ack_json.bin` | ACK selecting JSON encoding |
| `ack_msgpack.bin` | ACK selecting MsgPack encoding |
| `frame_channel_command.bin` | Data frame on ChannelCommand with JSON payload |
| `frame_oversized.bin` | Header with length = 16MiB+1 (must be rejected) |
| `frame_fragment_first.bin` | Fragment frame: `FLAG_FRAGMENT`, fragment_id=1 |
| `frame_fragment_last.bin` | Fragment frame: `FLAG_FRAGMENT \| FLAG_LAST_FRAG`, fragment_id=1 |
| `control_heartbeat.bin` | ChannelControl frame — `{"type":"heartbeat","ts":1748558400000}` |
| `control_error.bin` | ChannelControl frame — `{"type":"error","code":403,"message":"payload too large"}` |
| `control_ping.bin` | ChannelControl frame — `{"type":"ping","seq":1}` |
| `control_pong.bin` | ChannelControl frame — `{"type":"pong","seq":1}` |

---

## Versioning

The protocol version is an opaque `uint32`. Backward compatibility is not guaranteed across major version increments. A server receiving an unknown version **must** close without ACK.

Current version: **`2`** (spec: v2.final, released 2026-06-02)

---

## Conformance Checklist

A compliant implementation must:

- [ ] Send/receive the 16-byte handshake with all fields Big-Endian
- [ ] Reject connections with incorrect magic without sending ACK
- [ ] Reject connections with mismatched protocol version without sending ACK
- [ ] Support at minimum one encoding (JSON recommended as fallback)
- [ ] Enforce the 16 MiB payload cap on receive
- [ ] Normalize pipe names to ≤ 64 bytes before resolving transport address
- [ ] Use the OS temp directory API (not a hardcoded path)
- [ ] Clear read/write deadlines after handshake completion
- [ ] Treat `Flags = 0x00` frames as complete, unfragmented payloads
- [ ] Reassemble fragmented frames using `fragment_id` when `FLAG_FRAGMENT` is set
- [ ] Discard incomplete fragment sequences after the configured timeout (default 15 s) with `ERR_FRAGMENT_TIMEOUT (404)`
- [ ] Close the connection with `ERR_PROTOCOL_VIOLATION (403)` if the concurrent fragment cap is exceeded
- [ ] Send and respond to `heartbeat` messages on ChannelControl (JSON-encoded)
- [ ] Respond to `ping` with a `pong` carrying the same `seq` value
- [ ] Send an `error` Control message before closing the connection on protocol violations
- [ ] Silently ignore unknown `"type"` values on ChannelControl
- [ ] Create socket endpoints with `0600` permissions when supported by the platform
- [ ] Enforce PID strict mode when `expected_pid != 0` and reject mismatches with `ERR_PID_MISMATCH (402)` without ACK
