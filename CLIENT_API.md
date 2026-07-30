# Yuumi Client API Contract

Status: **alpha**

Wire protocol: **version `1`**

This document is the authoritative contract for the Yuumi client role. Only the
Go SDK implements it. The keywords **MUST**, **MUST NOT**, **SHOULD**,
**SHOULD NOT**, and **MAY** are normative.

The Client API is intentionally different from the [Engine API](./ENGINE_API.md).
Go is the logical client and also owns the local transport listener. It accepts
one engine dialer, sends the unchanged client handshake, and exposes the
established session to a terminal user interface. Listener ownership does not
make Go an engine or transfer engine-process lifecycle into Yuumi.

This contract has exactly one implementation and therefore prescribes concrete
Go signatures. A second spelling of the same behaviour would be divergence,
not an idiomatic variation.

---

## 1. Client configuration

```go
type ListenOptions struct {
    Heartbeat HeartbeatOptions
    RequestTimeout time.Duration
    MessageBuffer int
    ExpectedEnginePID *uint32
}
```

| Option | Contract |
|---|---|
| `Heartbeat` | Optional. It **MUST** carry `Disabled bool`, never `Enabled bool`, so the zero value keeps heartbeat active. |
| `RequestTimeout` | Optional, default 30 s. It **MUST** be positive when set and applies only when the request context carries no deadline. |
| `MessageBuffer` | Optional, provisional default 64. It **MUST** be greater than zero when set. |
| `ExpectedEnginePID` | Optional additional peer check. `nil` disables it; a pointer to zero means PID zero and is not equivalent to absence. It is not primary authentication. |

Every option **MUST** have a usable zero value. Invalid configuration **MUST**
fail before Go probes, creates, removes, or changes an endpoint.

There is no session-capacity option. A listener permits exactly one established
engine session at a time. Reconnect and retry timing are application policy;
they are not listener options.

---

## 2. Required Client API surface

```go
type Token string

func GenerateToken() (Token, error)

func Listen(name string, token Token, opts ...ListenOptions) (*Listener, error)
func (l *Listener) Accept(ctx context.Context) (*Client, error)
func (l *Listener) OnError(fn func(error))
func (l *Listener) Close() error

func (c *Client) Request(ctx context.Context, data any, ch Channel) (any, Channel, error)
func (c *Client) Send(data any, ch Channel) error
func (c *Client) Messages() <-chan Message

func (c *Client) OnError(fn func(error))
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

`Listener` owns the endpoint and admission. Each `Client` value represents one
established Go-engine session and never changes its underlying connection.
`Listener.Close` and `Client.Close` therefore have different scope.

There are exactly three ways to observe inbound session traffic, and they
**MUST NOT** overlap: `Request` for correlated replies, `Messages` for
unsolicited traffic, and callbacks for SDK-owned Control or error events. An
SDK **MUST NOT** expose a blocking single-message read and **MUST NOT** require
an explicit call to start session dispatching.

All exported methods **MUST** be safe for concurrent use by multiple goroutines.

---

## 3. Token and canonical address

The token is the access capability described in `PROTOCOL.md`, not an
identifier. It **MUST** be a distinct named type so transposing it with the
endpoint name is a compile-time error.

`GenerateToken` **MUST** draw 128 bits from a cryptographically secure source
and return exactly 32 lowercase hexadecimal characters. The SDK **MUST NOT**
provide a default, placeholder, or fixed token.

`Listen` **MUST** validate name and token and derive the address byte for byte
as `PROTOCOL.md` prescribes. On Unix this includes the NUL-separated SHA-256
input and encoded-path byte bound. On Windows it includes the clear token in
the canonical Named Pipe name. Go **MUST NOT** accept an arbitrary full path in
place of the two validated inputs.

---

## 4. Listener lifecycle and endpoint ownership

`Listen` **MUST**, in order:

1. validate all configuration, `endpoint_name`, and token;
2. derive the canonical platform address;
3. probe an existing endpoint by attempting a connection;
4. refuse to replace a live listener;
5. remove a Unix socket node only after connection refusal proves it stale;
6. create a Unix domain stream socket on Linux/macOS or a byte-stream Named
   Pipe on Windows;
7. apply mode `0600`, or the intended-user ACL and remote-client rejection,
   before accepting traffic; and
8. return once the protected endpoint is ready.

Endpoint presence alone is never proof of life. A busy Named Pipe is not stale.
Windows has no filesystem pipe node to unlink.

Opening an already-open listener at the same address **MUST** fail without
disturbing the live owner. `Listener.Close` **MUST** stop admission, close any
active candidate and established session, wait until their work cannot emit a
new callback, release all transport resources, and unlink or release the owned
endpoint. Repeated close **MUST** be safe.

---

## 5. Accept and handshake

`Accept` waits for one valid engine candidate while no session is established.
Only one `Accept` call may be active. Calling it while another `Accept` is
active or while a session is established **MUST** fail explicitly.

For each candidate, Go **MUST**:

1. accept the transport connection;
2. perform mandatory peer checks and the optional `ExpectedEnginePID` check
   where trustworthy credentials are available;
3. send the unchanged 16-byte version 1 client handshake;
4. read and validate the unchanged 4-byte engine ACK;
5. receive and validate the engine session assignment; and
6. create the `Client`, replace the listener's local epoch, and start dispatch.

A candidate is not a session until all six steps succeed. A rejected candidate
**MUST** be closed and `Accept` **MUST** continue waiting; it does not consume
the listener's only session slot. `Accept` returns an error only when its
context ends, the listener closes, or the listener can no longer accept safely.
Candidate-specific failures **MUST** remain observable through typed listener
diagnostics even though admission continues.

The handshake is still Go to engine. Protocol version remains `1`; no handshake,
ACK, session-assignment, or frame byte changes because transport ownership was
inverted.

---

## 6. Session lifecycle and epochs

An accepted `Client` owns immutable selected encoding, negotiated capabilities,
`session_id`, and local `epoch`. Closing or losing the session destroys its
heartbeat, fragmentation, and pending-correlation state and releases the
listener slot.

The application may call `Accept` again after complete teardown. The next
success creates a new `Client`, performs a full handshake, receives a new
engine-assigned `session_id`, and replaces the local epoch. Epoch values are
opaque SDK state and are never transmitted. An operation created under an old
epoch **MUST NOT** send, complete, time out, or invoke session work against the
replacement.

Pending requests fail with a distinct session-lost error and are never retried
automatically. Session retry, engine restart, and application resynchronization
remain application policy.

---

## 7. Payloads, messages, and requests

Inbound payloads **MUST** use `any`; JSON and MessagePack both admit objects,
arrays, and scalars. `Decode` converts a decoded payload into a caller-supplied
typed value identically for either negotiated encoding.

`Messages` carries only complete unsolicited non-Control messages. Correlated
responses belong to their `Request`; Control traffic belongs to the SDK. The
channel **MUST** be buffered to `MessageBuffer`. A full buffer **MUST NOT**
block the read loop; the SDK drops that message and reports a distinct typed
error so loss is observable. `Client.Close` closes the channel after dispatch
has stopped.

`Request` requires negotiated `CAP_CORRELATION`, allocates an identifier within
the session, and waits for the matching response. It fails before writing when
correlation was not negotiated. The context deadline wins over
`RequestTimeout`; timeout releases the identifier. A late unmatched response
is discarded and never becomes another request's response or unsolicited
traffic. Concurrent requests **MUST** be supported.

`Send` and `Request` accept only client-output application channels from the
protocol channel table. Applications cannot forge Control traffic. Sequential
accepted sends for one `Client` preserve order.

---

## 8. Callback and error rules

`Listener.OnError` reports candidate failures while `Accept` continues and
listener-level transport failures. `Client.OnError` reports typed protocol,
transport, session, and dropped-message errors. `OnHeartbeat` reports inbound
heartbeats, which never appear on `Messages`. An unregistered callback is
ignored silently.

Callbacks **MUST NOT** run while holding a lock needed by a public method. A
slow callback **MUST NOT** block transport reads, writes, heartbeat, timeout, or
endpoint admission. No session callback may begin after that `Client` has
finished closing.

Configuration, endpoint, candidate, and established-session failures remain
distinguishable. No error may be replaced by an empty payload or success-shaped
fallback.

---

## 9. What the Client API does not cover

The following remain outside this contract:

- starting, stopping, supervising, discovering, or restarting an engine;
- finding an executable or capturing its stdout/stderr;
- deciding how the engine obtains endpoint name and token;
- application schemas, command routing, retries, and domain semantics; and
- packaging or distribution of application executables.

The Go repository may ship `Runner` as an optional helper, but it is not part of
this contract and is not required for conformance. Endpoint ownership is part
of the Client API; engine-process ownership is not.

---

## 10. Conformance boundary

An implementation conforms when it satisfies this contract and `PROTOCOL.md`,
verified by the canonical vectors and the
[`Client Conformance Suite`](./CLIENT_CONFORMANCE.md). Correct frame codecs do
not compensate for unsafe endpoint ownership, reversed handshake direction,
loss of the one-to-one slot after candidate rejection, or stale-epoch work.
