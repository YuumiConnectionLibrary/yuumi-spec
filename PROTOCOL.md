# Yuumi Wire Protocol — Specification v2

This document is the authoritative definition of the Yuumi IPC wire protocol.
All language implementations (Go, C++, Rust, Python, …) must conform to this spec.

---

## Overview

Yuumi is a binary IPC protocol over Unix domain sockets (`.sock` files).
It provides:

- **Handshake** — magic, version, and PID verification with encoding negotiation
- **Multiplexed channels** — 4 logical channels over a single connection
- **Dual encoding** — JSON or MessagePack, negotiated at handshake
- **Frame safety** — 16 MiB maximum payload to prevent OOM

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
| Flags | 5 | 1 B | Reserved, must be `0x00` |
| Payload | 6 | N B | Serialized message body |

**Maximum payload size: 16,777,216 bytes (16 MiB).** Frames exceeding this must be rejected with `ERR_PROTOCOL_VIOLATION (403)`.

---

## Channels

| Value | Name | Direction | Purpose |
|---|---|---|---|
| `0x00` | Control | Bidirectional | Handshake signaling, heartbeat, lifecycle |
| `0x01` | Command | Host → Sidecar | Commands, requests |
| `0x02` | Log | Sidecar → Host | Log output, diagnostics |
| `0x03` | Data | Bidirectional | Payload data exchange |

---

## Status Codes

Status codes identify protocol events in structured error types. They are **not transmitted on the wire** — they are internal diagnostics.

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
| 403 | ERR_PROTOCOL_VIOLATION | Invalid framing or payload too large |
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

---

## Versioning

The protocol version is an opaque `uint32`. Backward compatibility is not guaranteed across major version increments. A server receiving an unknown version **must** close without ACK.

Current version: **`2`**

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
