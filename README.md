# Yuumi

> Local IPC protocol for a Go shell and language-independent logic engines.

Yuumi is a lightweight wire protocol and SDK ecosystem that lets a Go frontend
(TUI or CLI) communicate with a logic engine written in another language over
platform-native local IPC. This repository is the canonical source of truth for
the wire protocol, public API contracts, and conformance vectors.

Status: **alpha**. Current protocol version: **`1`**.

---

## Architecture

```
┌──────────────────────────┐   Local stream transport   ┌────────────────────────────┐
│   Go frontend (TUI/CLI)  │ ◄────────────────────────► │   Logic engine             │
│   yuumi (client SDK)     │        Yuumi protocol      │   C++ / Python / Rust / TS │
└──────────────────────────┘                            └────────────────────────────┘
```

The protocol is **asymmetric by design**:

- The **Go SDK** (`yuumi`) is the only client and provides the UI-side API.
- The **engine SDKs** (`yuumi-cpp`, `yuumi-py`, `yuumi-rs`, and `yuumi-ts`)
  open the endpoint, accept sessions, validate handshakes, and host application
  logic.

## The two contracts

Yuumi does not have one public API shared by every SDK. It has two deliberately
different contracts:

- The **Client API** belongs only to the Go SDK.
- The **[Engine API](./ENGINE_API.md)** belongs to C++, Python, Rust, and
  TypeScript.

The Engine API is a language-neutral behavioural contract. It defines endpoint
lifecycle, session isolation, engine-side handshake negotiation, security,
events, and outbound sends without forcing identical method spellings across
languages.

---

## Connection lifecycle

```
Go client                                  Engine
   │                                         │
   │── Handshake (16 bytes, Big-Endian) ────►│ validate and negotiate
   │◄── ACK (4 bytes) ──────────────────────│
   │◄── Control: session ───────────────────│
   │                                        │
   │◄════ Per-session frames ══════════════►│
   │                                        │
   │── close ──────────────────────────────►│
```

---

## Wire format

### Handshake — client → server, 16 bytes (all fields Big-Endian)

| Bytes | Field | Value |
|---|---|---|
| 0–3 | Magic | `0x59554D49` ("YUMI" in ASCII) |
| 4–7 | Protocol version | `1` (uint32) |
| 8–11 | Client PID | uint32 |
| 12 | Encoding capabilities | `0x01`=JSON, `0x02`=MsgPack, `0x03`=both |
| 13–15 | Capability mask | 24-bit client capability advertisement |

### ACK — server → client, 4 bytes

| Bytes | Field |
|---|---|
| 0 | Selected encoding (`0x01` or `0x02`) |
| 1–3 | Negotiated capabilities (client mask intersected with engine mask) |

### Data frame — 6-byte header + payload

| Bytes | Field |
|---|---|
| 0–3 | Payload length in bytes (BE uint32, max 16 MiB) |
| 4 | Channel ID (see table below) |
| 5 | Fragmentation and optional correlation flags |
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
| **C++23** | [yuumi-cpp](https://github.com/YuumiConnectionLibrary/yuumi-cpp) | Engine | CMake + vcpkg |
| **Python 3.11+** | [yuumi-py](https://github.com/YuumiConnectionLibrary/yuumi-py) | Engine | `pip install yuumi-py` |
| **Rust** | [yuumi-rs](https://github.com/YuumiConnectionLibrary/yuumi-rs) | Engine | `cargo add yuumi` *(planned)* |
| **TypeScript** | [yuumi-ts](https://github.com/YuumiConnectionLibrary/yuumi-ts) | Engine | `npm install yuumi` *(planned)* |

All SDKs implement their role-specific contract and must pass the applicable
conformance tests. The four engine SDKs share the numbered
[`Engine Conformance Suite`](./ENGINE_CONFORMANCE.md). Wire conformance is
proven with the canonical vectors in [`test-vectors/`](./test-vectors/).

---

## Technical choices

**Platform-native local streams** — Unix domain sockets on Linux/macOS and Named
Pipes on Windows. TCP and transport fallback are forbidden. The deterministic
address includes a 128-bit token and uses the platform temporary-directory API
where applicable.

**Binary handshake (16 bytes)** — the protocol version is a compatibility gate,
the PID can be checked optionally, and a 24-bit mask negotiates additive
capabilities.

**Dual encoding: JSON + MsgPack** — the engine selects one common encoding from
the masks exchanged during handshake.

**16 MiB payload cap** — frame lengths are validated before allocation and both
frame and reassembled-message overflow use `ERR_PAYLOAD_TOO_LARGE (413)`.

**Channel multiplexing** — four logical channels share each session's local
stream, separating Control traffic from application data.

**Isolated sessions** — every accepted connection owns its negotiated encoding,
capabilities, heartbeat state, fragmentation buffers, correlation state,
`session_id`, and local `epoch`.

**Capabilities, not version bumps** — additive features are enabled only by the
intersection of endpoint capability masks. Library semver remains independent.

---

## Conformance test vectors

Every `.bin` fixture in [`test-vectors/`](./test-vectors/) has a same-basename
`.json` annotation with exact bytes, offsets, context, and expected behaviour.
The complete canonical vector inventory is maintained in
[`PROTOCOL.md`](./PROTOCOL.md#canonical-test-vectors).

Engine acceptance is defined by
[`ENGINE_CONFORMANCE.md`](./ENGINE_CONFORMANCE.md), which distinguishes
baseline tests from tests that run only after capability negotiation.

---

## Versioning

Protocol version is a plain integer compatibility gate in the handshake.
Current version: **`1`**. Additive features use capability bits; incompatible
wire changes increment the protocol version and regenerate the vectors. Each SDK
uses its own independent library semver.

---

## Issues

Questions about the protocol specification? [Open an issue](https://github.com/YuumiConnectionLibrary/yuumi-spec/issues) in this repository. For SDK-specific questions, open an issue in the relevant SDK repository.
