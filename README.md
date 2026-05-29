# Yuumi

> Binary IPC protocol for multi-process applications — one socket, multiple channels, two encodings.

Yuumi is a lightweight wire protocol and SDK ecosystem that lets a Go frontend (TUI, CLI) communicate with a backend written in **any language** over a local Unix socket. This repository is the canonical source of truth: it contains the protocol specification and the conformance test vectors that all implementations must pass.

---

## Architecture

```
┌──────────────────────────┐    Unix socket (.sock)    ┌────────────────────────────┐
│   Go frontend (TUI/CLI)  │ ◄───────────────────────► │   Backend server           │
│   yuumi (client SDK)     │     Yuumi v2 protocol      │   C++ / Python / Rust / …  │
└──────────────────────────┘                            └────────────────────────────┘
```

The protocol is **asymmetric by design**:

- The **Go SDK** (`yuumi`) is the *client* — it dials the socket, sends the handshake, and drives the UI layer. It can also start and stop the server binary via `Runner`.
- The **server SDKs** (`yuumi-cpp`, `yuumi-py`, `yuumi-rs`, …) listen on the socket, validate the handshake, and handle application logic.

---

## Connection lifecycle

```
Client (Go)                              Server (C++ / Python / …)
   │                                              │
   │── Handshake (16 bytes, Big-Endian) ────────►│  validate magic, version, PID
   │◄── ACK (4 bytes) ──────────────────────────│  select encoding (JSON or MsgPack)
   │                                              │
   │◄══ Data frames (bidirectional) ══════════════│
   │                                              │
   │── close ───────────────────────────────────►│
```

---

## Wire format

### Handshake — client → server, 16 bytes (all fields Big-Endian)

| Bytes | Field | Value |
|---|---|---|
| 0–3 | Magic | `0x59554D49` ("YUMI" in ASCII) |
| 4–7 | Protocol version | `2` (uint32) |
| 8–11 | Client PID | uint32 |
| 12 | Encoding capabilities | `0x01`=JSON, `0x02`=MsgPack, `0x03`=both |
| 13–15 | Reserved | `0x000000` (must be zero) |

### ACK — server → client, 4 bytes

| Bytes | Field |
|---|---|
| 0 | Selected encoding (`0x01` or `0x02`) |
| 1–3 | Reserved (`0x00`, must be zero) |

### Data frame — 6-byte header + payload

| Bytes | Field |
|---|---|
| 0–3 | Payload length in bytes (BE uint32, max 16 MiB) |
| 4 | Channel ID (see table below) |
| 5 | Flags (must be `0x00`) |
| 6+ | Payload — JSON or MsgPack object |

### Channels

| ID | Name | Direction | Purpose |
|---|---|---|---|
| `0x00` | Control | Bidirectional | Heartbeat (`{"type":"heartbeat","ts":<unix>}`), lifecycle |
| `0x01` | Command | Client → Server | Commands, requests |
| `0x02` | Log | Server → Client | Log output, diagnostics |
| `0x03` | Data | Bidirectional | Application payload |

Full specification → [`PROTOCOL.md`](./PROTOCOL.md)

---

## SDK ecosystem

| Language | Repo | Role | Install |
|---|---|---|---|
| **Go** | [yuumi](https://github.com/YuumiConnectionLibrary/yuumi) | Client / TUI side | `go get github.com/YuumiConnectionLibrary/yuumi` |
| **C++23** | [yuumi-cpp](https://github.com/YuumiConnectionLibrary/yuumi-cpp) | Server side | CMake + vcpkg |
| **Python 3.11+** | [yuumi-py](https://github.com/YuumiConnectionLibrary/yuumi-py) | Server / scripting | `pip install yuumi-py` |
| **Rust** | [yuumi-rs](https://github.com/YuumiConnectionLibrary/yuumi-rs) | Server / CLI tools | `cargo add yuumi` *(planned)* |
| **TypeScript** | [yuumi-ts](https://github.com/YuumiConnectionLibrary/yuumi-ts) | Server / Node tools | `npm install yuumi` *(planned)* |

All SDKs expose the same public API surface and must pass the conformance test vectors in [`test-vectors/`](./test-vectors/).

---

## Technical choices

**Unix domain sockets** — zero-copy local IPC, no network stack, no firewall rules. Available on Linux, macOS, and Windows 10 1803+ (`AF_UNIX`). Socket path is always `<os_temp_dir>/<pipe_name>.sock` with the pipe name capped at 64 UTF-8 bytes.

**Binary handshake (16 bytes)** — PID field allows the server to reject connections from unexpected processes. The version field enables protocol evolution without breaking existing deployments.

**Dual encoding: JSON + MsgPack** — JSON for human-readable debugging and broad interoperability; MsgPack for production throughput (~30 % smaller payloads, no string parsing). The server selects one encoding from the client's capability bitmask during handshake.

**16 MiB payload cap** — enforced on receive to prevent OOM from malformed or adversarial frames. Frames exceeding the limit must be rejected with `ERR_PROTOCOL_VIOLATION (403)`.

**Channel multiplexing** — four logical channels over a single socket connection, separating control traffic (heartbeat) from application data without the overhead of multiple connections.

**Heartbeat on ChannelControl** — `{"type":"heartbeat","ts":<unix_timestamp>}` frames are dispatched to a dedicated `on_heartbeat` callback in every SDK, keeping them out of the application message stream.

**Exponential backoff with jitter** — all SDKs expose a `ReconnectPolicy` type (initial delay, max delay, max attempts, ±10 % jitter) to handle transient server startup delays.

---

## Conformance test vectors

| File | Description |
|---|---|
| `handshake_valid.bin` | Valid handshake, version=2, JSON+MsgPack caps, PID=1234 |
| `handshake_bad_magic.bin` | Magic = `0xDEADBEEF` — must be rejected without ACK |
| `ack_json.bin` | ACK selecting JSON encoding |
| `ack_msgpack.bin` | ACK selecting MsgPack encoding |
| `frame_channel_command.bin` | Data frame on ChannelCommand with JSON payload `{"action":"test"}` |
| `frame_oversized.bin` | Length = 16 MiB+1 — must trigger `ERR_PROTOCOL_VIOLATION (403)` |

---

## Versioning

Protocol version is an opaque `uint32` in the handshake. Current version: **2**.
Breaking wire changes must increment the version and refresh all test vectors.

---

## Issues

Questions about the protocol specification? [Open an issue](https://github.com/YuumiConnectionLibrary/yuumi-spec/issues) in this repository. For SDK-specific questions, open an issue in the relevant SDK repository.
