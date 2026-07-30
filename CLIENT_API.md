# Yuumi Go Client API Contract

Status: **alpha**

Wire protocol: **version `1`**

This document is the normative contract for the Go Client API. Go is the only
logical client and the only listener. The keywords **MUST**, **MUST NOT**,
**SHOULD**, **SHOULD NOT**, and **MAY** are normative.

The Client API owns the protected local endpoint and IPC session. It does not
own the engine process. Listener ownership does not change handshake direction:
Go sends the handshake and an engine dialer returns ACK and session assignment.

---

## 1. Responsibilities and exclusions

- **CLI-ROLE-001** — Go validates configuration, derives and protects the
  endpoint, accepts candidates, sends the handshake, validates ACK and session
  assignment, and owns framing, correlation, fragmentation, heartbeat, epoch,
  and cleanup on its side.
- **CLI-ROLE-002** — A transport candidate is not a session until handshake,
  ACK, and session assignment all succeed.
- **CLI-ROLE-003** — The client accepts a new candidate after rejection or a
  completed session disconnect without recreating the Go client object.
- **CLI-ROLE-004** — The API never starts, stops, discovers, supervises, or
  restarts an engine; chooses an executable; or captures stdout/stderr.
- **CLI-ROLE-005** — `Runner`, environment handoff, retry policy, process
  policy, and application schemas are optional application helpers outside this
  contract and outside client conformance.

---

## 2. Concrete Go surface

The one Go implementation uses these names and semantic shapes:

```go
type Token string

type Config struct {
	EndpointName string
	Token Token
	Listen ListenOptions
}

type ListenOptions struct {
	Heartbeat HeartbeatOptions
	RequestTimeout time.Duration
	MessageBuffer int
	CallbackBuffer int
	ExpectedEnginePID *uint32
	SupportedEncodings []Encoding
	DisabledCapabilities Capabilities
}

type HeartbeatOptions struct {
	Interval time.Duration
	MissThreshold int
	Disabled bool
}

type SessionView struct {
	SessionID string
	Epoch uint64
	Encoding Encoding
	Capabilities Capabilities
}

type Message struct {
	Data any
	Channel Channel
	Epoch uint64
}

type HeartbeatEvent struct {
	Session SessionView
	Timestamp int64
}

type DisconnectEvent struct {
	Session SessionView
	Reason DisconnectReason
	Err error
}

func GenerateToken() (Token, error)
func NewClient(cfg Config) (*Client, error)
func (c *Client) Open() error
func (c *Client) WaitConnected(ctx context.Context) (SessionView, error)
func (c *Client) Send(data any, ch Channel) error
func (c *Client) Request(ctx context.Context, data any, ch Channel) (any, Channel, error)
func (c *Client) Messages() <-chan Message
func (c *Client) Session() (SessionView, bool)
func (c *Client) OnConnected(fn func(SessionView))
func (c *Client) OnDisconnected(fn func(DisconnectEvent))
func (c *Client) OnHeartbeat(fn func(HeartbeatEvent))
func (c *Client) OnError(fn func(error))
func (c *Client) Close() error
func Decode(data any, dst any) error
```

- **CLI-API-001** — `GenerateToken` obtains 128 cryptographically secure bits
  and returns exactly 32 lowercase hexadecimal characters. No default or fixed
  token exists.
- **CLI-API-002** — `NewClient` validates and copies configuration but performs
  no probe, bind, listen, unlink, accept, dial, or goroutine start.
- **CLI-API-003** — `Open` creates and protects the endpoint, starts admission,
  and returns when listening is ready. It never waits for an engine.
- **CLI-API-004** — `WaitConnected` returns the current session if connected;
  while listening it waits for the next established session or context/client
  closure. Multiple waiters are allowed and observe the same next session.
- **CLI-API-005** — `Send` and `Request` accept only client-output `Command` and
  `Data`. Control frames cannot be forged through public API.
- **CLI-API-006** — `Messages` is the only stream for complete unsolicited
  application messages. Correlated replies go only to `Request`; Control goes
  only to SDK state/callbacks.
- **CLI-API-007** — `Session` returns an immutable snapshot and `false` outside
  `connected`. All exported methods are safe for concurrent goroutine use.
- **CLI-API-008** — `Close` is idempotent and permanently closes the object.
  Reopening a closed client is forbidden and fails with `closed`.
- **CLI-API-009** — `Decode` converts a decoded JSON or MessagePack value into
  `dst` without imposing an application envelope. Nil or invalid destinations
  fail explicitly.

The required fields have no meaningful zero value and are validated. Every
optional field does:

| Option | Zero-value/default behaviour |
|---|---|
| **CLI-CFG-001** `Heartbeat.Disabled` | `false`; heartbeat enabled. |
| **CLI-CFG-002** `Heartbeat.Interval` | 30 s; a negative value is invalid. |
| **CLI-CFG-003** `Heartbeat.MissThreshold` | 3; a negative value is invalid. |
| **CLI-CFG-004** `RequestTimeout` | 30 s; a negative value is invalid. A request context deadline takes precedence. |
| **CLI-CFG-005** `MessageBuffer` | **64**; a negative value is invalid. |
| **CLI-CFG-006** `CallbackBuffer` | **64**; a negative value is invalid. |
| **CLI-CFG-007** `ExpectedEnginePID` | `nil` disables the additional check; pointer-to-zero is a real value. |
| **CLI-CFG-008** `SupportedEncodings` | `nil` means the set MessagePack and JSON; slice order is not transmitted. Non-nil empty, duplicates, and unknown values are invalid. |
| **CLI-CFG-009** `DisabledCapabilities` | Zero disables nothing. Only implemented capability bits may be named; version 1 advertises `CAP_CORRELATION` unless disabled. |

For integer/duration options, zero selects the documented default; an explicit
negative value is invalid. Configuration errors occur before transport access.
There is no reconnect, session-capacity, executable, or arbitrary-address
option.

---

## 3. Normative state machine

```text
          Open succeeds
 +-----+ ----------------> +-----------+
 | new |                   | listening | <---------+
 +-----+ <---------------- +-----------+           |
          Open fails           |                   |
                               | valid candidate   | session loss
                               v                   |
                           +-----------+           |
                           | connected | ----------+
                           +-----------+
                                |
             Close from any live state
                                v
                           +---------+  teardown  +--------+
                           | closing | ---------> | closed |
                           +---------+            +--------+
```

| State | Invariant |
|---|---|
| **CLI-STATE-001** `new` | Configured object, no endpoint or background work. |
| **CLI-STATE-002** `listening` | Protected endpoint and accept loop are active; no established session. |
| **CLI-STATE-003** `connected` | Exactly one established engine session is active. Additional candidates are rejected without affecting it. |
| **CLI-STATE-004** `closing` | New operations fail; candidate, session, listener, waits, queues, and goroutines are being stopped. |
| **CLI-STATE-005** `closed` | All owned resources are released. `Open` is permanently forbidden. |

- **CLI-STATE-006** — `Open` is valid only in `new`. A failed open restores
  `new` after cleaning partial resources, so the application may retry.
- **CLI-STATE-007** — An invalid candidate is closed and returns the client to
  or leaves it in `listening`; it never consumes the only session slot.
- **CLI-STATE-008** — Session loss returns to `listening` without starting,
  stopping, or restarting any process.
- **CLI-STATE-009** — Every established session receives the engine's new
  `session_id` and a client-local epoch strictly greater than the prior
  successful epoch. Epoch zero means no session and is never transmitted.
- **CLI-STATE-010** — Sends, responders, request timers, fragments,
  correlations, queued events, and callbacks capture an epoch. Stale work fails
  or is discarded and cannot reach, mutate, emit against, or close a later
  session.

---

## 4. Endpoint security and ownership

- **CLI-ENDP-001** — `NewClient` validates the endpoint name and token and
  derives the canonical address byte-for-byte as `PROTOCOL.md` specifies,
  including OS temp lookup, filesystem encoding, and macOS pathname byte bound.
- **CLI-ENDP-002** — `Open` probes an existing endpoint by connecting. A live
  endpoint is never replaced. Presence alone does not prove liveness, and a
  busy Named Pipe is not stale.
- **CLI-ENDP-003** — On Unix, a socket node is unlinked before bind only after
  connection refusal proves it stale. A listener-owned node is unlinked during
  shutdown. No unrelated path is removed.
- **CLI-ENDP-004** — Linux/macOS create a Unix domain stream socket with mode
  `0600` before traffic. Windows creates a byte-stream Named Pipe through
  `Microsoft/go-winio`, restricts ACL to the intended user, and rejects remote
  clients before traffic.
- **CLI-ENDP-005** — TCP, network fallback, hardcoded temp directories, token
  case folding, arbitrary full paths, and token/address disclosure in routine
  diagnostics are forbidden.
- **CLI-ENDP-006** — `Close` releases the listener, active candidate, session,
  Unix node or Windows handles, goroutines, timers, queues, and blocked waits.

---

## 5. Candidate admission and establishment

- **CLI-ADMIT-001** — While `listening`, Go accepts and evaluates one candidate
  at a time and sends the exact 16-byte client handshake only after mandatory
  transport security/peer checks succeed.
- **CLI-ADMIT-002** — Go validates the exact 4-byte ACK selection and capability
  subset, then validates the immediately following session assignment before
  entering `connected`.
- **CLI-ADMIT-003** — Short/invalid ACK, unadvertised encoding/capability,
  malformed assignment, peer-check failure, or candidate disconnect closes
  only that candidate, emits a typed listener diagnostic, and admission
  continues.
- **CLI-ADMIT-004** — Candidate rejection emits neither connected nor
  disconnected. The connected callback and `WaitConnected` release occur only
  after dispatch is ready for the established session.
- **CLI-ADMIT-005** — While `connected`, later candidates are refused or
  accepted only to be immediately closed without handshake. They cannot change
  session state, epoch, callbacks, or negotiated values.
- **CLI-ADMIT-006** — A fatal accept-loop error is observable, closes owned
  resources, and transitions through `closing` to `closed`; it is not presented
  as an engine disconnect.

---

## 6. Session operations and cleanup

- **CLI-SESS-001** — `Send` writes an uncorrelated frame with the current
  encoding. Completed success means the bytes were written; sequential calls
  preserve order.
- **CLI-SESS-002** — `Request` requires negotiated `CAP_CORRELATION`, allocates
  a session-unique `uint32` ID, writes the correlated request, and waits only
  for the matching response. Concurrent requests are supported.
- **CLI-SESS-003** — Context deadline overrides the configured request timeout.
  Timeout releases the ID. A late unmatched reply is discarded and never
  reaches `Messages` or another request.
- **CLI-SESS-004** — Disconnect fails all pending requests with
  `session_closed` carrying the lost epoch. `Close` fails them with `closed`.
  Requests are never retried automatically.
- **CLI-SESS-005** — Already accepted application events for the old epoch are
  delivered in order before its disconnected callback. Establishment of a new
  session may proceed at transport level, but its connected application event
  is ordered after the prior disconnected event.
- **CLI-SESS-006** — Disconnect discards partial fragments, unmatched
  correlations, unsent output, timers, and SDK-internal state. It does not
  discard already accepted application events unless `Close` is in progress.
- **CLI-SESS-007** — `Close` rejects new operations, unblocks `WaitConnected`
  and requests, stops admission and session I/O, closes `Messages` after
  dispatch stops, and prevents any later callback from starting.

---

## 7. Dispatch, callbacks, and backpressure

Accept, transport I/O, parsing, writes, heartbeat, timeouts, and close do not
share an application callback path.

- **CLI-DISP-001** — Complete messages for one epoch are offered to `Messages`
  in wire order. Session callbacks are started in event order and never overlap
  each other.
- **CLI-DISP-002** — `Messages` and the callback queue are both bounded by their
  configured capacities, each defaulting to 64. IPC never waits indefinitely
  for either queue.
- **CLI-DISP-003** — If either queue is full, the client records a typed
  `backpressure` error, stops accepting application work for that epoch, closes
  the session, fails pending requests, and returns to `listening` after ordered
  disconnection. It does not drop a message and continue successfully.
- **CLI-DISP-004** — Terminal error/disconnected delivery has reserved internal
  capacity outside `CallbackBuffer`, so backpressure remains observable.
- **CLI-DISP-005** — Heartbeat, error, connected, and disconnected callbacks run
  without locks needed by public methods. An absent callback is a no-op.
- **CLI-DISP-006** — A callback panic is recovered at the SDK dispatch boundary,
  reported as typed `application` error, and never converted to success. A
  panic in `OnError` is reported once through Go's runtime panic reporting and
  is not recursively dispatched.
- **CLI-DISP-007** — `Close` invoked outside a callback waits for dispatch and
  goroutines to end. When invoked by the currently running callback, it closes
  transport and prevents new callbacks, but cannot wait for itself; resource
  completion occurs as that callback returns.

---

## 8. Error model

Errors are concrete Go types usable with `errors.Is`/`errors.As`. Each carries
an English cause and the phase/epoch when applicable.

| Kind | Produced when |
|---|---|
| **CLI-ERR-001** `configuration` | Required or optional configuration is invalid. |
| **CLI-ERR-002** `address_derivation` | Temp lookup, hashing, filesystem encoding, or path-byte validation fails. |
| **CLI-ERR-003** `endpoint_live` | Another live listener owns the canonical endpoint. |
| **CLI-ERR-004** `security` | Mode, ACL, remote rejection, or peer credential validation fails. |
| **CLI-ERR-005** `accept` | Listener admission fails terminally. |
| **CLI-ERR-006** `handshake` | Candidate transport, ACK, or session assignment fails. |
| **CLI-ERR-007** `protocol` | Established framing, channel, Control, correlation, or fragmentation is invalid. |
| **CLI-ERR-008** `encoding` | ACK selects an invalid encoding or codec work fails. |
| **CLI-ERR-009** `capability` | ACK exceeds the offer or an operation needs an unnegotiated capability. |
| **CLI-ERR-010** `timeout` | Request, heartbeat, fragment, read, or write deadline expires. |
| **CLI-ERR-011** `backpressure` | `Messages` or callback capacity is exhausted; terminal for that epoch. |
| **CLI-ERR-012** `session_closed` | An operation targets no active session or one lost by disconnect. |
| **CLI-ERR-013** `stale_epoch` | Old work attempts to act on a replacement session. |
| **CLI-ERR-014** `closed` | The client is closing/closed or `Close` cancels work. |
| **CLI-ERR-015** `application` | An application callback panics. |
| **CLI-ERR-016** `transport` | Established read/write/close fails without a more specific kind. |
| **CLI-ERR-017** `internal` | An invariant or runtime facility fails and no specific kind applies. |
| **CLI-ERR-018** `state` | `Open` is called outside `new` or another operation is invalid for the current non-closed state. |

Candidate diagnostics have no epoch and do not terminate `WaitConnected`.
Established fatal errors carry their epoch, are reported once, and are not
replaced by empty data or a normal result.

---

## 9. Current Go API disposition

| Keep or adapt | Replace | Explicitly outside/remove from contract |
|---|---|---|
| `Token`, `GenerateToken`, `Send`, `Request`, `Messages`, `Decode`, protocol value types, typed errors | `Connect` -> `NewClient` + `Open`; `ConnectOptions` -> `Config`/`ListenOptions`; `OnReconnect` -> `OnConnected` and `OnDisconnected`; drop-on-full -> terminal backpressure; reconnecting `Client` internals -> listener admission state machine | `ReconnectPolicy`, automatic reconnect/backoff, `Runner`, executable/log capture, engine process control, public non-Go clients |

`Runner` may remain a separately documented application convenience in the Go
repository, but importing or using it is never required by this contract or its
conformance suite.

---

## 10. Conformance trace

The [`Client Conformance Contract`](./CLIENT_CONFORMANCE.md) and
[`conformance/manifest.json`](./conformance/manifest.json) supply the executable
wire, endpoint, platform, dispatch, and cleanup cases. The manifest references
every concrete `CLI-*` identifier. Its exact flat mapping is validated and can
be printed with:

```text
python tools/conformance_tool.py --coverage
```

The mapping is deliberately generated instead of maintained as wildcard ranges
in two documents. Validation fails if a requirement is missing, an identifier
is duplicated, a vector does not exist, or a mandatory platform case can be
skipped. The contract remains implementable with ordinary Go goroutines and
`Microsoft/go-winio`; it requires no engine lifecycle helper.
