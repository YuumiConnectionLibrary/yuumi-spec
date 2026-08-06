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
┌────────────────────────────┐   Local stream transport   ┌────────────────────────────┐
│ Go frontend (TUI/CLI)      │ ◄────────────────────────► │ Logic engine               │
│ logical client + listener  │        Yuumi protocol      │ C++ / Python / Rust / TS   │
└────────────────────────────┘                            │ engine + dialer            │
                                                        └────────────────────────────┘
```

The protocol is **asymmetric by design**:

- The **Go SDK** (`yuumi`) is the only logical client, owns the listener, and
  provides the UI-side API.
- The **engine SDKs** (`yuumi-cpp`, `yuumi-py`, `yuumi-rs`, and `yuumi-ts`)
  dial the Go endpoint, validate the received handshake, send ACK and session
  assignment, and host application logic.

Transport ownership does not define process ownership. Yuumi does not spawn,
discover, restart, supervise, package, or capture output from an engine.

## The two contracts

Yuumi does not have one public API shared by every SDK. It has two deliberately
different contracts:

- The **[Client API](./CLIENT_API.md)** belongs only to the Go SDK.
- The **[Engine API](./ENGINE_API.md)** belongs to C++, Python, Rust, and
  TypeScript.

The Engine API is a language-neutral behavioural contract. It defines address
derivation, dialling, received-handshake negotiation, session isolation,
events, and outbound sends without forcing identical method spellings.

The Client API has a single implementation and therefore prescribes concrete Go
signatures. It defines endpoint creation and protection, candidate admission,
client-side negotiation, the three non-overlapping inbound paths, correlated
requests, and replacement-session semantics.

---

## Connection lifecycle

```
Go logical client + listener               Engine + dialer
   │                                         │
   │ open and protect endpoint               │
   │◄──────────── connect ───────────────────│
   │ accept candidate                        │
   │── Handshake (16 bytes, Big-Endian) ────►│ validate and negotiate
   │◄── ACK (4 bytes) ───────────────────────│
   │◄── Control: session ────────────────────│
   │                                         │
   │◄════ Per-session frames ═══════════════►│
```

Exactly one engine session is established at a time. A rejected candidate is
closed without consuming the slot, so Go continues accepting. Reconnection is
a new session with a new assignment and replaced opaque local epoch.

---

## Wire format

### Handshake — Go logical client → engine, 16 bytes (all fields Big-Endian)

| Bytes | Field | Value |
|---|---|---|
| 0–3 | Magic | `0x59554D49` ("YUMI" in ASCII) |
| 4–7 | Protocol version | `1` (uint32) |
| 8–11 | Client PID | uint32 |
| 12 | Encoding capabilities | `0x01`=JSON, `0x02`=MsgPack, `0x03`=both |
| 13–15 | Capability mask | 24-bit client capability advertisement |

### ACK — engine → Go logical client, 4 bytes

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
| `0x01` | Command | Go → engine | Commands, requests |
| `0x02` | Log | Engine → Go | Log output, diagnostics |
| `0x03` | Data | Bidirectional | Application payload |

Full specification → [`PROTOCOL.md`](./PROTOCOL.md)

---

## SDK ecosystem

| Language | Repo | Role | Install |
|---|---|---|---|
| **Go** | [yuumi](https://github.com/YuumiConnectionLibrary/yuumi) | Logical client + listener | `go get github.com/YuumiConnectionLibrary/yuumi` |
| **C++23** | [yuumi-cpp](https://github.com/YuumiConnectionLibrary/yuumi-cpp) | Engine + dialer | CMake + vcpkg |
| **Python** | [yuumi-py](https://github.com/YuumiConnectionLibrary/yuumi-py) | Engine + dialer | `pip install yuumi-py` |
| **Rust** | [yuumi-rs](https://github.com/YuumiConnectionLibrary/yuumi-rs) | Engine + dialer | `cargo add yuumi` *(planned)* |
| **TypeScript** | [yuumi-ts](https://github.com/YuumiConnectionLibrary/yuumi-ts) | Engine + dialer | `npm install yuumi` *(planned)* |

All SDKs implement their role-specific contract and must pass the applicable
conformance cases. Go uses the
[`Client Conformance Contract`](./CLIENT_CONFORMANCE.md); the four engine SDKs
share the [`Engine Conformance Contract`](./ENGINE_CONFORMANCE.md). Their case
inventory and exact requirement mapping live in
[`conformance/manifest.json`](./conformance/manifest.json). Wire conformance is
proven with the canonical vectors in [`test-vectors/`](./test-vectors/).

---

## Technical choices

**Platform-native local streams** — Go listens on a Unix domain socket on
Linux/macOS and a byte-stream Named Pipe on Windows; every engine dials it. TCP
and transport fallback are forbidden. Windows carries the token in the pipe
name. Unix uses `yuumi-<digest>.sock`, where `digest` is the first 32 lowercase
hex characters of SHA-256 over `yuumi\0<endpoint_name>\0<token>` UTF-8 bytes.

**Binary handshake (16 bytes)** — the protocol version is a compatibility gate,
the PID can be checked optionally, and a 24-bit mask negotiates additive
capabilities.

**Dual encoding: JSON + MsgPack** — the engine selects one common encoding from
the masks exchanged during handshake.

**16 MiB payload cap** — frame lengths are validated before allocation and both
frame and reassembled-message overflow use `ERR_PAYLOAD_TOO_LARGE (413)`.

**Channel multiplexing** — four logical channels share each session's local
stream, separating Control traffic from application data.

**One isolated session** — one established engine at a time owns negotiated
encoding, capabilities, heartbeat state, fragmentation buffers, correlation
state, `session_id`, and an opaque local `epoch`. Rejected candidates do not
consume the slot.

**Capabilities, not version bumps** — additive features are enabled only by the
intersection of endpoint capability masks. Library semver remains independent.

---

## Conformance test vectors

Every `.bin` fixture in [`test-vectors/`](./test-vectors/) has a same-basename
`.json` annotation with exact bytes, offsets, context, and expected behaviour.
The complete canonical vector inventory is maintained in
[`PROTOCOL.md`](./PROTOCOL.md#canonical-test-vectors).

Address derivation uses the machine-readable
[`address_derivation.json`](./test-vectors/address_derivation.json). The
generated [`manifest.json`](./test-vectors/manifest.json) classifies every wire
fixture and pins binary and annotation SHA-256 values. Validate the frozen
vectors and both conformance contracts with:

```text
python tools/vector_tool.py
python tools/conformance_tool.py --self-test
```

Go acceptance is defined by
[`CLIENT_CONFORMANCE.md`](./CLIENT_CONFORMANCE.md). Engine acceptance is
defined by [`ENGINE_CONFORMANCE.md`](./ENGINE_CONFORMANCE.md). Print the exact
flat requirement-to-case mapping with
`python tools/conformance_tool.py --coverage`.

---

## Versioning

Protocol version is a plain integer compatibility gate in the handshake.
Current version: **`1`**. Additive features use capability bits; incompatible
wire changes increment the protocol version and regenerate the vectors. Each SDK
uses its own independent library semver.

---

## Issues

Questions about the protocol specification? [Open an issue](https://github.com/YuumiConnectionLibrary/yuumi-spec/issues) in this repository. For SDK-specific questions, open an issue in the relevant SDK repository.

Organization CI ownership is documented in [`CI.md`](CI.md). The executable
cell report contract and local harness are documented in
[`conformance/README.md`](conformance/README.md).
