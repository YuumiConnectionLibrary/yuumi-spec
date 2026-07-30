# Yuumi Client Conformance Suite

Status: **alpha**

Wire protocol: **version `1`**

This document is the executable acceptance suite for the Go Client API. Every
test is mandatory on Windows, Linux, and macOS unless its assertion names one
platform. The normative sources are [`PROTOCOL.md`](./PROTOCOL.md) and
[`CLIENT_API.md`](./CLIENT_API.md); if they disagree with this suite, the
contract wins and this suite must be corrected.

---

## 1. Harness contract

The harness uses a private engine dialer, never a public non-Go client. It must
be able to connect to the Go listener, split reads and writes at arbitrary byte
offsets, send exact vector bytes, inspect endpoint access controls, inject
listener/accept/read/write failures, and observe attempted allocation before a
declared payload is read. Timing checks use bounded deadlines, not sleeps.

Task 01 changes transport ownership and address derivation only. Existing
handshake, ACK, Control, and frame vectors remain byte-for-byte unchanged.
Task 02 adds address fixtures for the canonical examples in `PROTOCOL.md` and
confirms every current `.bin` fixture unchanged.

---

## 2. Configuration, address, endpoint, and security

1. **CC-001 — Invalid configuration has no endpoint side effects**
   - Invalid names, tokens, option values, and an overlong Unix pathname fail
     before probe, bind, unlink, listener handle creation, or worker startup.

2. **CC-002 — Canonical address derivation is byte-identical**
   - The minimum and maximum examples reproduce their documented SHA-256
     prefixes. Unix uses `yuumi-<digest>.sock`; Windows uses the clear-token
     pipe name. No SDK case-folds, normalizes, truncates, or relocates input.

3. **CC-003 — macOS path budget is enforced in bytes**
   - The documented 59-byte temporary directory produces a 103-byte pathname
     and is accepted. Adding one `b` produces 104 bytes and fails before bind.

4. **CC-004 — Go opens the platform listener and applies security first**
   - Linux/macOS expose a Unix domain stream socket with mode `0600`. Windows
     exposes a byte-stream Named Pipe with intended-user ACL and remote-client
     rejection. No TCP listener or fallback exists, and no candidate can reach
     handshake traffic before protection is active.

5. **CC-005 — A live endpoint is never replaced**
   - A second `Listen` probes the live endpoint, fails, and leaves the first
     listener usable. A busy Named Pipe is not stale.

6. **CC-006 — Cleanup follows proved refusal only**
   - A Unix socket node is unlinked only after a connection refusal proves no
     listener owns it. Windows releases handles and never attempts filesystem
     unlink. Mere endpoint presence does not trigger cleanup.

7. **CC-007 — Listener close owns deterministic teardown**
   - Close stops admission, terminates candidates and the active session,
     prevents later callbacks, releases all resources, and removes/releases the
     endpoint. Repeated close is safe and the address can be opened again.

---

## 3. Candidate admission and establishment

8. **CC-008 — Go sends the exact version 1 handshake after accept**
   - Before transport accept, the dialer receives no bytes. After accept it
     reads exactly `handshake_valid.bin` or `handshake_cap_correlation.bin`,
     including the Go PID. Protocol version is `1`.

9. **CC-009 — ACK and session assignment complete establishment**
   - The candidate returns `ack_json.bin` or `ack_msgpack.bin`, followed
     immediately by `control_session.bin`. `Accept` returns a ready `Client`
     only after both are validated and dispatch has started.

10. **CC-010 — Invalid candidates do not consume the slot**
    - In separate attempts, the dialer disconnects, returns a short/invalid ACK,
      advertises an unoffered selection, or sends `control_session_empty_id.bin`.
      Go closes each candidate, reports the typed cause, keeps `Accept` active,
      and subsequently establishes one valid engine.

11. **CC-011 — One established session is mandatory**
    - While one `Client` is established, a second `Accept` fails and another
      dialer cannot establish. After complete session teardown, a new `Accept`
      may establish exactly one replacement.

12. **CC-012 — Context and fatal listener failures end Accept**
    - Context expiry closes only the current candidate and returns its context
      error while leaving the listener reusable. Listener close and an injected
      fatal accept failure return distinct typed errors and do not report a
      session.

13. **CC-013 — Optional engine PID is an additional check**
    - Absence disables filtering; explicit zero differs from absence. Where
      trustworthy client credentials exist, mismatch closes before handshake,
      reports `ERR_PID_MISMATCH (402)`, and does not consume the slot. Token and
      OS controls remain mandatory.

---

## 4. Session, frame, Control, and epoch behaviour

14. **CC-014 — Negotiation and application traffic preserve existing vectors**
    - ACK capability intersection, channels, correlation, fragmentation,
      payload bounds, Control JSON, and status-code boundaries pass every
      applicable existing canonical vector without byte changes.

15. **CC-015 — Decoder validates length before read or allocation**
    - `frame_oversized.bin` causes `ERR_PAYLOAD_TOO_LARGE (413)`, a safe
      `control_error.bin`, and close without requesting or allocating the
      declared 16 MiB-plus-one payload.

16. **CC-016 — Inbound paths do not overlap**
    - Correlated responses reach only `Request`; complete unsolicited payloads
      reach only `Messages`; Control reaches only SDK callbacks/state. Partial,
      malformed, wrong-direction, and Control frames never become application
      messages or success-shaped payloads.

17. **CC-017 — Slow consumers do not stop IPC**
    - A full message buffer reports one typed dropped-message error and does not
      block reads, heartbeat, writes, timeout handling, or listener admission.
      Slow callbacks obey the same isolation.

18. **CC-018 — Requests are session-scoped**
    - Correlation fails before writing when not negotiated. Concurrent requests
      retain distinct IDs; completion and timeout release IDs; late unmatched
      responses are discarded and never routed to `Messages` or a newer
      request.

19. **CC-019 — Replacement session replaces all local generation state**
    - After disconnect, pending requests fail and old buffers are discarded.
      A later `Accept` performs a new handshake, adopts the new engine-assigned
      ID, and uses a different opaque epoch that never appears on the wire.

20. **CC-020 — Stale work cannot act on a replacement**
    - Sends, responders, callbacks, timeouts, fragment work, and correlations
      captured from the old `Client` fail or are discarded. They write no bytes,
      emit no event, and cannot close or mutate the replacement.

21. **CC-021 — Public boundary contains no lifecycle policy**
   - The public contract exposes `Listen`, `Accept`, session operations, and
     typed listener diagnostics plus deterministic close. It does not require
     spawn, discovery, restart, stdout/stderr capture, packaging, an
     application envelope, or `Runner`.

---

## 5. Normative coverage

| Contract area | Tests |
|---|---|
| Configuration and address derivation | CC-001 through CC-003 |
| Endpoint ownership, security, stale cleanup, and close | CC-004 through CC-007 |
| Accept, handshake direction, candidate rejection, and 1:1 slot | CC-008 through CC-013 |
| Unchanged wire and defensive decoding | CC-014, CC-015 |
| Dispatch, correlation, and callback isolation | CC-016 through CC-018 |
| Session replacement and opaque epoch | CC-019, CC-020 |
| Public product boundary | CC-021 |
