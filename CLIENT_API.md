# Yuumi Client API Contract

Status: **alpha**

Wire protocol: **version `1`**

This document is the authoritative contract for the Yuumi client role. Only the
Go SDK implements it. The keywords **MUST**, **MUST NOT**, **SHOULD**,
**SHOULD NOT**, and **MAY** are normative.

The Client API is intentionally different from the [Engine API](./ENGINE_API.md).
It derives an endpoint address, dials it, negotiates a session, and exposes that
session to a terminal user interface. It never listens and never accepts
connections.

Unlike the Engine API, which is language-neutral because four SDKs implement it,
this contract has exactly one implementation. It therefore prescribes concrete Go
signatures: a second spelling of the same behaviour would be a divergence, not an
idiomatic variation.

---

## 1. Client configuration

```go
type ConnectOptions struct {
    Reconnect ReconnectPolicy
    Heartbeat HeartbeatOptions
    RequestTimeout time.Duration
    MessageBuffer int
}
```

| Option | Contract |
|---|---|
| `Reconnect` | Optional. The zero value **MUST** mean no reconnection attempt. |
| `Heartbeat` | Optional. It **MUST** carry `Disabled bool`, never `Enabled bool`, so that the zero value keeps heartbeat active. |
| `RequestTimeout` | Optional, default 30 s. It **MUST** be positive when set and applies only when the request context carries no deadline. |
| `MessageBuffer` | Optional, provisional default 64. It **MUST** be greater than zero when set. |

Every option **MUST** have a usable zero value. A caller that passes no options
**MUST** obtain a working client with protocol-recommended defaults.

Invalid configuration **MUST** fail before any transport operation is attempted.

---

## 2. Required Client API surface

```go
type Token string

func GenerateToken() (Token, error)

func Connect(name string, token Token, opts ...ConnectOptions) (*Client, error)

func (c *Client) Request(ctx context.Context, data any, ch Channel) (any, Channel, error)
func (c *Client) Send(data any, ch Channel) error
func (c *Client) Messages() <-chan Message

func (c *Client) OnError(fn func(error))
func (c *Client) OnReconnect(fn func(sessionID string, epoch uint64))
func (c *Client) OnHeartbeat(fn func(ts int64))

func (c *Client) SessionID() string
func (c *Client) Epoch() uint64
func (c *Client) NegotiatedCapabilities() Capabilities
func (c *Client) Close() error

func Decode(data any, v any) error

type Message struct {
    Data any
    Channel Channel
}
```

There are exactly three ways to observe inbound traffic, and they **MUST NOT**
overlap: `Request` for correlated replies, `Messages` for unsolicited traffic,
and the lifecycle callbacks for connection events. An SDK **MUST NOT** expose a
blocking single-message read, and **MUST NOT** require an explicit call to start
dispatching.

All exported methods **MUST** be safe for concurrent use by multiple goroutines.

---

## 3. Token and address

The token is the access capability described in `PROTOCOL.md`, not an
identifier. It **MUST** be a distinct named type so that transposing it with the
endpoint name is a compile-time error.

`GenerateToken` **MUST** draw 128 bits from a cryptographically secure source and
return them as exactly 32 lowercase hexadecimal characters. Callers **SHOULD**
obtain tokens this way; an SDK **MUST NOT** provide a default, placeholder, or
fixed token.

`Connect` **MUST** validate name and token, then derive the address exactly as
`PROTOCOL.md` prescribes, so that client and engine agree byte for byte. It
**MUST NOT** create, modify, or remove an endpoint: endpoint ownership belongs to
the engine.

---

## 4. Payload representation

Inbound payload values **MUST** be typed `any`, on `Request`, on `Messages`, and
anywhere else a decoded payload is surfaced. The wire admits objects, arrays, and
scalars in both encodings; a signature narrower than the wire would make valid
traffic unrepresentable.

`Decode` **MUST** convert a decoded payload into a caller-supplied typed value,
behaving identically whichever encoding was negotiated. It exists so that
applications move from wire values to their own types without asserting and
indexing untyped maps.

---

## 5. Connection and handshake

`Connect` **MUST**, in order: validate configuration, derive the address, dial
the transport, send the 16-byte handshake, read the 4-byte ACK, validate the
negotiated encoding and capabilities, receive the session assignment, and start
dispatching.

It **MUST** fail, without leaving a goroutine or an open descriptor behind, when
the address cannot be derived, the transport refuses or is stale, the ACK is
malformed, or the ACK sets an encoding or capability the client did not
advertise.

The dispatch loop **MUST** start as part of a successful `Connect`. Messages that
arrive before the caller reads from `Messages` **MUST** be buffered, not dropped
for lack of a reader.

---

## 6. Message stream

`Messages` returns a receive-only channel of unsolicited traffic. It **MUST**
carry only messages that are neither correlated responses nor Control messages:
a correlated response belongs to its `Request` caller, and Control traffic
belongs to the lifecycle callbacks.

The channel **MUST** be buffered to `MessageBuffer`. When the buffer is full the
SDK **MUST NOT** block the read loop, because stalling it also stalls heartbeat
handling and would turn a slow consumer into a dropped connection. It **MUST**
instead drop the message and report the loss through `OnError` with a distinct
error, so that loss is observable rather than silent.

> The buffer size and the overflow policy are provisional. They are a
> deliberate default chosen to be safe under load, not a measured one, and are
> revisited once throughput measurements exist.

`Close` **MUST** close the channel after the read loop has stopped, so that a
ranging consumer terminates.

---

## 7. Request and response

`Request` sends a correlated message and waits for the response carrying the same
`correlation_id`.

It **MUST** fail immediately, before sending anything, when `CAP_CORRELATION` was
not negotiated. Waiting for a reply that the engine cannot produce would surface
a configuration error as a timeout.

Identifier handling **MUST** follow `PROTOCOL.md`: allocation is incremental
within the session, an identifier is never reused while pending, and it is
released on completion, failure, or timeout.

The deadline is the context deadline when the context carries one, and
`RequestTimeout` otherwise; the context always wins. On expiry the call **MUST**
fail with a distinct timeout error and release its identifier.

A response that arrives after its request completed **MUST** be discarded. It
**MUST NOT** be delivered to another request and **MUST NOT** be diverted to
`Messages`, where it would appear as unsolicited traffic.

`Request` **MUST** support concurrent callers: serialising it would defeat the
purpose of correlation.

---

## 8. Lifecycle events

| Callback | Contract |
|---|---|
| `OnError` | Protocol, transport, and session errors, and dropped-message notifications. Errors **MUST** be typed so that callers can distinguish causes without matching strings. |
| `OnReconnect` | Invoked after a replacement session is established, carrying the new `session_id` and the incremented `epoch`. |
| `OnHeartbeat` | Invoked for inbound heartbeats. Heartbeats **MUST NOT** also appear on `Messages`. |

Callbacks are optional. An unregistered callback **MUST** be ignored silently.
A callback **MUST NOT** be invoked while holding a lock that a client method
needs, so that calling back into the client cannot deadlock.

---

## 9. Reconnection

Reconnection produces a new session, never a continuation of the old one. On a
successful replacement connection the SDK **MUST** discard the previous
negotiated state and fragment buffers, renegotiate encoding and capabilities,
adopt the new `session_id`, increment `epoch`, and invoke `OnReconnect`.

Requests still pending when the session drops **MUST** fail with a distinct
session-lost error. They **MUST NOT** be retried automatically and **MUST NOT**
remain pending across sessions: their identifiers belonged to a session that no
longer exists, and the engine has no memory of them.

This is deliberate. The user interface has to resynchronise against the new
session rather than assume continuity, and only the application knows which work
is safe to reissue.

---

## 10. What the Client API does not cover

The following are outside this contract, and an implementation **MUST NOT**
present them as part of it:

- **Engine process lifecycle.** Starting, stopping, supervising, or restarting an
  engine is application policy. The Go SDK ships `Runner` as an optional
  convenience; it is not part of this contract, and no engine SDK is required to
  offer an equivalent.
- **Endpoint ownership.** Creating and removing endpoints belongs to the engine.
- **Discovery.** Deciding which engine to reach, and how a name and token are
  agreed, is application concern.
- **Application semantics.** Message meaning, schemas, and retry policy are
  application concerns. The client carries payloads; it does not interpret them.

---

## 11. Conformance boundary

An implementation conforms when it satisfies this contract and the wire rules in
`PROTOCOL.md`, verified against the canonical test vectors.

A client that dials and exchanges frames but does not enforce the separation of
the three inbound paths, the fail-fast on unnegotiated correlation, or the
session-lost failure of pending requests does not conform. These rules are the
contract; frame codec correctness alone is not sufficient.
