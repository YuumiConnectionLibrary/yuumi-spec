# Yuumi Engine Conformance Suite

Status: **alpha**

Wire protocol: **version `1`**

This document is the single acceptance suite for the C++, Python, Rust, and
TypeScript engine SDKs. An SDK conforms only when it passes every applicable
test below on every supported platform. The suite verifies observable
behaviour; it does not require identical public method names or internal
architecture.

The normative sources remain [`PROTOCOL.md`](./PROTOCOL.md) and
[`ENGINE_API.md`](./ENGINE_API.md). If this suite and either contract disagree,
the contract wins and the suite must be corrected.

---

## 1. Applicability and result classes

Every test has one of these classes:

- **Baseline**: mandatory for every engine SDK.
- **`CAP_CORRELATION`**: run only in a session whose ACK negotiated
  `CAP_CORRELATION`.

Protocol version 1 Engine API implementations are required to implement
`CAP_CORRELATION`. Therefore, the capability-gated tests are part of version 1
acceptance even though their traffic is valid only after negotiation. A failed
or skipped capability test is a conformance failure when the engine advertised
that capability.

Platform-specific assertions are mandatory on their platform:

| Platform | Required endpoint assertions |
|---|---|
| Linux | Unix domain stream socket, OS temporary directory, mode `0600` |
| macOS | Unix domain stream socket, OS temporary directory, mode `0600` |
| Windows | byte-stream Named Pipe, intended-user ACL, remote clients rejected |

Tests that require a trustworthy peer-credential API apply where the platform
and runtime expose one. Lack of such an API does not remove the mandatory token,
endpoint ACL, or optional `expected_pid` checks.

---

## 2. Harness contract

Each SDK may provide an idiomatic test adapter, but the same observations must
be available in all four languages:

- configure, open, and close an engine through its public Engine API;
- register all four event kinds and record their payload and start order;
- connect one or more private test peers over the platform-required transport;
- send exact bytes, split writes at arbitrary offsets, and stop before sending
  a declared payload;
- read exact engine output and detect EOF, timeout, or additional bytes;
- inspect endpoint type and platform access controls;
- inject transport accept, read, ACK-write, session-write, and post-accept
  failures through test-only seams;
- observe attempted payload reads and allocations for decoder-boundary tests;
- use shortened positive heartbeat and fragmentation timeouts; and
- record peak process memory or an equivalent SDK-local allocation probe when
  a test explicitly requires proof that an oversized buffer was not allocated.

The private peer is test infrastructure, not public non-Go client API.
Fault-injection seams also remain internal to the SDK testkit.

Each `.bin` fixture is consumed byte-for-byte. Its same-basename `.json` file is
the oracle for fields, context, and expected status. `Canonical vectors: none`
means the harness constructs the bytes described by the test because no
canonical fixture currently applies.

A test passes only when all expected wire output, public results, events,
resource effects, and negative observations occur. Timing assertions use an
eventually-within-deadline check and must never depend on an unbounded sleep.

---

## 3. Configuration, endpoint, and security

1. **EC-001 — Invalid configuration has no endpoint side effects**
   - Class: **Baseline**.
   - Precondition: No engine owns the canonical endpoint. Prepare separate
     configurations with an invalid `endpoint_name`, invalid token, zero or
     negative `max_sessions`, duplicate or unknown encodings, an empty encoding
     list, an unimplemented or reserved capability, an out-of-range
     `expected_pid`, a non-positive enabled heartbeat value, and a non-positive
     fragmentation value.
   - Action: Attempt to construct or open the engine once for every invalid
     configuration.
   - Expected: Every attempt fails explicitly before creating, removing, or
     changing an endpoint. No accept worker starts and no success-shaped result
     or event is emitted.
   - Canonical vectors: none.

2. **EC-002 — Canonical address and platform transport**
   - Class: **Baseline**.
   - Precondition: Use a valid endpoint name and token and obtain the temporary
     directory from the operating-system API.
   - Action: Open the engine and inspect the bound endpoint.
   - Expected: Linux and macOS use a Unix domain stream socket at exactly
     `<os_temp_dir>/yuumi-<endpoint_name>-<token>.sock`; Windows uses exactly
     `\\.\pipe\yuumi-<endpoint_name>-<token>` in byte-stream mode. Case,
     separators, name, and token are unchanged. No TCP listener or fallback
     transport exists.
   - Canonical vectors: none.

3. **EC-003 — Address bounds are rejected, never rewritten**
   - Class: **Baseline**.
   - Precondition: On Unix, select a valid name and token whose canonical path
     exceeds the platform socket-address bound because of the OS-provided
     temporary directory. On every platform, prepare values at and immediately
     outside their declared validation bounds.
   - Action: Attempt to open the endpoint.
   - Expected: Boundary-valid values are preserved exactly. Invalid or
     overlong values fail explicitly before bind. No value is truncated,
     hashed, case-folded, normalized, or relocated to a hardcoded temporary
     directory.
   - Canonical vectors: none.

4. **EC-004 — Engine defaults are protocol-conforming**
   - Class: **Baseline**.
   - Precondition: Configure only required values and register events.
   - Action: Open the engine; connect one peer advertising JSON and MessagePack
     plus `CAP_CORRELATION`, then keep that session open and attempt a second
     connection.
   - Expected: The selected encoding is MessagePack, the ACK negotiates
     `CAP_CORRELATION`, the first session has epoch `0`, and the second
     connection is refused because default `max_sessions` is `1`. Default
     heartbeat settings equal the recommendations in `PROTOCOL.md`.
   - Canonical vectors: `handshake_cap_correlation.bin`,
     `ack_cap_correlation.bin`, `control_session.bin`.

5. **EC-005 — Open, mutation, and repeated close state rules**
   - Class: **Baseline**.
   - Precondition: Create a valid closed engine.
   - Action: Open it, attempt a second open, attempt to mutate address,
     security, negotiation, and capacity configuration, close it, then close it
     again.
   - Expected: The first open succeeds as soon as the secured endpoint is ready
     and does not wait for a client. The second open and every prohibited
     mutation fail explicitly without affecting the live endpoint. Both close
     calls are safe; the second is an idempotent no-op or equivalent successful
     closed-state result.
   - Canonical vectors: none.

6. **EC-006 — A live endpoint is never replaced**
   - Class: **Baseline**.
   - Precondition: A first engine is listening at the canonical endpoint and
     can accept a valid session.
   - Action: Open a second engine with the same endpoint name and token, then
     connect a peer to the first engine.
   - Expected: The second open probes the endpoint, detects a live owner, and
     fails without removing or replacing it. The first engine remains usable
     and accepts the peer normally. A busy Windows pipe is not classified as
     stale while a server instance can still accept.
   - Canonical vectors: `handshake_valid.bin`.

7. **EC-007 — A stale endpoint is removed or released before recreation**
   - Class: **Baseline**.
   - Precondition: On Unix, leave a socket node with no live listener at the
     canonical path. On Windows, terminate the owning server or close a
     test-owned stale server handle so no live listener owns the canonical pipe.
   - Action: Open a new engine at the same canonical address and connect a peer.
   - Expected: The engine first establishes that connection is refused, then
     unlinks the Unix node or releases the Windows handle as appropriate, binds
     the same canonical address, and accepts the peer. It never treats endpoint
     presence alone as proof of life.
   - Canonical vectors: `handshake_valid.bin`.

8. **EC-008 — Access controls precede handshake traffic**
   - Class: **Baseline**.
   - Precondition: Register an accept observer and prepare both an intended-user
     peer and, where the test environment permits it, a different-user or
     remote Windows peer.
   - Action: Open the engine, inspect endpoint security before sending a
     handshake, and attempt both peer connections.
   - Expected: A Unix socket node is mode `0600`. A Windows Named Pipe security
     descriptor grants the intended local user and rejects remote clients. The
     intended peer can connect only after the control is in place; no handshake
     bytes are accepted earlier.
   - Canonical vectors: `handshake_valid.bin`.

9. **EC-009 — A wrong token cannot reach the handshake**
   - Class: **Baseline**.
   - Precondition: Open an engine with token A and derive the canonical address
     for the same endpoint name with different valid token B.
   - Action: Attempt a transport connection to the token-B address and watch
     the token-A engine output and events.
   - Expected: The transport connection to token B fails because it names a
     different endpoint. The engine receives no handshake, emits no ACK,
     Control frame, connected event, or handshake error. The token is not a
     handshake field and is not emulated as one.
   - Canonical vectors: none.

10. **EC-010 — Orderly close releases all owned state**
    - Class: **Baseline**.
    - Precondition: Open an engine with at least two established sessions and
      active heartbeat and fragment state.
    - Action: Close the engine and, while it is closing, attempt a new
      connection and new application sends.
    - Expected: Admission stops first. Existing sessions each emit exactly one
      orderly-engine-close disconnect event, all workers and transport
      resources stop, all state is discarded, and no callback begins after
      close completes. The Unix node or final pipe server handle is gone and a
      fresh engine can acquire the same address.
    - Canonical vectors: `handshake_cap_correlation.bin`,
      `frame_fragment_correlated_first.bin`.

11. **EC-011 — Token diagnostics and public address surface are safe**
    - Class: **Baseline**.
    - Precondition: Enable all SDK diagnostics and prepare configuration and
      endpoint failures involving a known token.
    - Action: Trigger the failures and inspect public constructors, builders,
      options, error text, and diagnostic records.
    - Expected: The public API requires `endpoint_name` and `token` and does not
      accept an arbitrary full transport path in their place. Diagnostics
      redact the token unless a documented operation strictly needs the
      complete address; routine configuration and transport errors do not print
      it.
   - Canonical vectors: none.

---

## 4. Handshake and session establishment

12. **EC-012 — Valid JSON handshake produces the exact ACK**
    - Class: **Baseline**.
    - Precondition: Configure JSON as the engine's first supported preference,
      disable additive capabilities for this run, and open the endpoint.
    - Action: Send `handshake_valid.bin` and read engine output.
    - Expected: The engine reads all 16 bytes, writes exactly `ack_json.bin`,
      writes a valid session Control frame immediately afterward, and only then
      emits one connected event whose immutable view matches the negotiated
      state.
    - Canonical vectors: `handshake_valid.bin`, `ack_json.bin`,
      `control_session.bin`.

13. **EC-013 — Valid MessagePack handshake produces the exact ACK**
    - Class: **Baseline**.
    - Precondition: Configure MessagePack as the first supported preference and
      disable additive capabilities for this run.
    - Action: Send `handshake_valid.bin` and read engine output.
    - Expected: The first four output bytes are exactly `ack_msgpack.bin`.
      Session assignment follows before any application or heartbeat frame, and
      the connected view records MessagePack.
    - Canonical vectors: `handshake_valid.bin`, `ack_msgpack.bin`,
      `control_session.bin`.

14. **EC-014 — A short handshake is never parsed as complete**
    - Class: **Baseline**.
    - Precondition: Open an engine and prepare every non-empty prefix shorter
      than 16 bytes plus an empty connection.
    - Action: Send each prefix of `handshake_valid.bin`, then close or trigger
      the configured pre-session read timeout.
    - Expected: Every connection closes with no ACK, Control frame, connected
      event, or disconnected event. One observable pre-session error identifies
      the read/transport phase and has no session handle.
    - Canonical vectors: `handshake_valid.bin` used as truncated prefixes.

15. **EC-015 — Invalid magic is rejected without ACK**
    - Class: **Baseline**.
    - Precondition: Open an engine with capacity for one pre-session
      connection.
    - Action: Send `handshake_bad_magic.bin`.
    - Expected: The engine reports `ERR_MAGIC_MISMATCH (400)`, sends zero bytes,
      closes the connection, emits no session events, and releases the capacity
      slot only after teardown completes.
    - Canonical vectors: `handshake_bad_magic.bin`.

16. **EC-016 — Incompatible version is rejected without ACK**
    - Class: **Baseline**.
    - Precondition: Open an engine.
    - Action: Send `handshake_bad_version.bin`.
    - Expected: The engine reports `ERR_VERSION_MISMATCH (401)`, sends neither
      an ACK nor a Control error, closes, and emits no session events. Library
      semantic version metadata does not change this decision.
    - Canonical vectors: `handshake_bad_version.bin`.

17. **EC-017 — Empty encoding intersection is rejected without ACK**
    - Class: **Baseline**.
    - Precondition: Configure the engine for JSON only.
    - Action: Send `handshake_encoding_unsupported.bin`.
    - Expected: The engine reports `ERR_ENCODING_UNSUPPORTED (415)`, writes no
      bytes, closes, and emits no connected or disconnected event.
    - Canonical vectors: `handshake_encoding_unsupported.bin`.

18. **EC-018 — `expected_pid` absence, zero, and mismatch are distinct**
    - Class: **Baseline**.
    - Precondition: Prepare three engines: no `expected_pid`, explicit
      `expected_pid = 0`, and `expected_pid = 1235`. Prepare valid handshakes
      whose PID fields are respectively arbitrary, zero, and `1234`.
    - Action: Connect once to each engine. Where trustworthy peer credentials
      exist, also send a PID different from the authenticated peer PID.
    - Expected: Absence disables PID filtering. Explicit zero accepts only a
      zero PID subject to trustworthy credential checks. The configured and
      trustworthy-credential mismatches report `ERR_PID_MISMATCH (402)` and
      close without ACK or session events. Token and OS access controls remain
      active in every case.
    - Canonical vectors: `handshake_valid.bin` as the base packet; the harness
      replaces only the PID field.

19. **EC-019 — Encoding preference and reserved bits are deterministic**
    - Class: **Baseline**.
    - Precondition: Prepare engines with preference orders JSON/MessagePack and
      MessagePack/JSON. Prepare a valid handshake advertising both known bits
      and, in a separate run, additional reserved encoding bits.
    - Action: Send the handshakes and inspect each ACK.
    - Expected: The engine selects the first configured known encoding present
      in the client mask. Reserved bits are never selected and do not change the
      known-bit intersection. Exactly one encoding bit appears in every ACK.
    - Canonical vectors: `handshake_valid.bin`, `ack_json.bin`,
      `ack_msgpack.bin`; the reserved-bit case is constructed by the harness.

20. **EC-020 — Shared correlation capability is negotiated by intersection**
    - Class: **Baseline**.
    - Precondition: Configure engine support for `CAP_CORRELATION`.
    - Action: Send `handshake_cap_correlation.bin`.
    - Expected: ACK bytes 1-3 are exactly the Big-Endian intersection in
      `ack_cap_correlation.bin`; the connected view exposes the same immutable
      mask and correlated frames are enabled only for this session.
    - Canonical vectors: `handshake_cap_correlation.bin`,
      `ack_cap_correlation.bin`.

21. **EC-021 — No shared capability still establishes a baseline session**
    - Class: **Baseline**.
    - Precondition: Disable engine capabilities for this run while the peer
      advertises `CAP_CORRELATION`.
    - Action: Send `handshake_cap_correlation.bin`.
    - Expected: The engine sends `ack_capabilities_none.bin`, establishes the
      session, and leaves correlation disabled. Lack of a shared additive
      capability is not a handshake failure.
    - Canonical vectors: `handshake_cap_correlation.bin`,
      `ack_capabilities_none.bin`.

22. **EC-022 — Unknown capability bits are excluded and ignored**
    - Class: **Baseline**.
    - Precondition: Configure only implemented version 1 capabilities and
      prepare a valid handshake containing `CAP_CORRELATION` plus unknown or
      reserved capability bits.
    - Action: Send the handshake and inspect the ACK and connected view.
    - Expected: The ACK contains only
      `client_capabilities & supported_capabilities & 0x000001`. Unknown bits
      neither appear in the ACK nor reject an otherwise valid handshake.
    - Canonical vectors: `handshake_cap_correlation.bin` as the base packet;
      the harness sets reserved mask bits.

23. **EC-023 — Establishment write failures never create a visible session**
    - Class: **Baseline**.
    - Precondition: Install one fault that fails or partially writes the ACK and
      another that fails the session Control write after a complete ACK.
    - Action: Complete a valid handshake under each fault.
    - Expected: An ACK failure closes immediately and never produces a valid
      partial ACK. A post-ACK session-assignment failure closes without a
      connected or disconnected event. Each terminal failure is reported once
      with phase and cause, and all reserved capacity is released after
      teardown.
    - Canonical vectors: `handshake_valid.bin`, `ack_json.bin`,
      `control_session.bin`.

---

## 5. Capacity, session state, and events

24. **EC-024 — `max_sessions = 1` counts pre-session connections**
    - Class: **Baseline**.
    - Precondition: Open an engine with `max_sessions = 1`.
    - Action: Hold the first connection after fewer than 16 handshake bytes,
      then connect a second peer and send a valid handshake.
    - Expected: The first connection owns the only slot. The second closes with
      no ACK, Control frame, or session event. Once the first connection is
      completely torn down, a new valid peer can establish a session.
    - Canonical vectors: `handshake_valid.bin`, including a truncated prefix.

25. **EC-025 — `max_sessions = N` accepts N concurrent isolated sessions**
    - Class: **Baseline**.
    - Precondition: Open an engine with `max_sessions = 3`.
    - Action: Establish three sessions concurrently, attempt a fourth, close
      one established session, and retry the fourth peer.
    - Expected: Exactly three sessions establish. The excess connection closes
      without ACK or session event. Capacity is not reused until teardown is
      complete; afterward one replacement session establishes without
      disturbing the two survivors.
    - Canonical vectors: `handshake_valid.bin`, `ack_json.bin`,
      `control_session.bin`.

26. **EC-026 — Negotiated and heartbeat state is session-local**
    - Class: **`CAP_CORRELATION`**.
    - Precondition: Allow two sessions. Negotiate JSON without correlation in
      one and MessagePack with correlation in the other; give only the first
      session recent heartbeat activity.
    - Action: Exchange valid application and heartbeat traffic concurrently.
    - Expected: Each connected view and decoder retains its own encoding and
      capability mask. Heartbeat counters and deadlines do not reset across
      sessions. Activity or timeout in one session does not alter or close the
      other.
    - Canonical vectors: `handshake_valid.bin`,
      `handshake_cap_correlation.bin`, `ack_json.bin`,
      `ack_cap_correlation.bin`, `control_heartbeat.bin`.

27. **EC-027 — Session assignment is ordered, valid, and unique**
    - Class: **Baseline**.
    - Precondition: Allow at least two sessions and record raw output and event
      start order.
    - Action: Establish both sessions.
    - Expected: Each ACK is followed immediately by exactly one JSON Control
      session frame before any other frame. Each `session_id` is printable
      ASCII, non-empty, at most 128 bytes, opaque to the peer, and unique among
      active sessions. The connected event starts only after that frame was
      written and exposes the same ID.
    - Canonical vectors: `control_session.bin` as the structural oracle;
      `control_session_empty_id.bin` as the invalid boundary oracle.

28. **EC-028 — Channel, fragment, and correlation identifiers are isolated**
    - Class: **`CAP_CORRELATION`**.
    - Precondition: Establish two correlation-enabled sessions.
    - Action: On both sessions, use channel `0x03`, fragment ID `7`, and
      correlation ID `42` with different payloads and interleaved timing.
    - Expected: Two independent messages are assembled and dispatched to their
      own session handles. No buffer, pending identifier, response, error, or
      payload crosses the session boundary.
    - Canonical vectors: `frame_fragment_correlated_first.bin`,
      `frame_fragment_correlated_last.bin`; one session's data bytes are
      replaced by the harness.

29. **EC-029 — Reconnection creates a new ID, higher epoch, and empty state**
    - Class: **Baseline**.
    - Precondition: Establish a first session at epoch `0`, leave a partial
      fragment and heartbeat state, then disconnect it.
    - Action: Reconnect through the same engine capacity slot and complete a
      fresh handshake.
    - Expected: The replacement receives a different `session_id` and an epoch
      greater than `0`, renegotiates from the new handshake, and starts with
      empty heartbeat and fragment state. The epoch never appears on the wire,
      and no old partial message completes in the replacement session.
    - Canonical vectors: `handshake_valid.bin`, `frame_fragment_first.bin`,
      `control_session.bin`.

30. **EC-030 — Stale handles and delayed work cannot address a replacement**
    - Class: **Baseline**.
    - Precondition: Save a first session handle, disconnect it, and establish a
      replacement that may reuse internal storage.
    - Action: Attempt sends with the old handle and release delayed callback,
      timeout, fragment, and correlation work tagged with the old epoch.
    - Expected: Every stale operation is rejected or discarded. Nothing is
      delivered to, emitted by, or used to close the replacement session. The
      public handle identifies both `session_id` and `epoch`.
    - Canonical vectors: none.

31. **EC-031 — Per-session event order and serialization are stable**
    - Class: **Baseline**.
    - Precondition: Register callbacks that record start/end times and block the
      first application callback briefly through a harness barrier.
    - Action: Establish a session, send two valid messages, release the barrier,
      and disconnect.
    - Expected: Event start order is connected, two message events, then
      disconnected. No two application callbacks for that session overlap.
      The connected event occurs exactly once and its session view is immutable.
      Events from a second session may interleave without violating either
      session's local order.
    - Canonical vectors: `frame_channel_command.bin`.

32. **EC-032 — Disconnect event is exact and reasoned**
    - Class: **Baseline**.
    - Precondition: Prepare established sessions for orderly engine close, peer
      close, heartbeat timeout, fatal protocol failure, and injected transport
      failure.
    - Action: Trigger each cause in a separate run.
    - Expected: Every session that emitted connected emits exactly one
      disconnected event with its final handle and the matching distinct reason.
      No message callback begins afterward. Rejected handshakes emit neither
      connected nor disconnected.
    - Canonical vectors: `handshake_bad_magic.bin`,
      `frame_correlated_not_negotiated.bin`.

33. **EC-033 — Endpoint and session failures remain isolated**
    - Class: **Baseline**.
    - Precondition: Keep two healthy sessions established and install separate
      accept and per-session read/write faults.
    - Action: Trigger an accept failure, then a fatal fault in only one session.
    - Expected: The accept error has no session handle and does not terminate
      healthy sessions while accepting remains safe. The session error carries
      only its session handle and closes only that session. The other session
      continues to send and receive.
    - Canonical vectors: `frame_channel_command.bin`.

34. **EC-034 — Only complete valid non-Control messages reach the application**
    - Class: **Baseline**.
    - Precondition: Establish a session and record all message events.
    - Action: Send a Control frame, a partial fragment, malformed encoded
      payload, a direction violation, and a fatal protocol error in separate
      runs, plus one valid complete application frame.
    - Expected: Exactly the valid complete non-Control frame produces one
      message event with live handle, channel, decoded payload, and no
      correlation value. None of the other inputs appears as an application
      message or an empty/success fallback.
    - Canonical vectors: `control_heartbeat.bin`,
      `frame_fragment_first.bin`, `frame_channel_command.bin`.

---

## 6. Frame validation and fragmentation

35. **EC-035 — Complete JSON command dispatch**
    - Class: **Baseline**.
    - Precondition: Establish a JSON session.
    - Action: Send `frame_channel_command.bin`.
    - Expected: The engine dispatches exactly one Command message with the
      decoded JSON payload, no prefix interpretation, and no correlation ID.
    - Canonical vectors: `frame_channel_command.bin`.

36. **EC-036 — Complete MessagePack command dispatch**
    - Class: **Baseline**.
    - Precondition: Establish a MessagePack session and prepare a valid
      MessagePack object in a Command frame.
    - Action: Send the complete frame.
    - Expected: The engine decodes with the negotiated MessagePack codec and
      dispatches exactly one message. It does not parse the application payload
      as JSON.
    - Canonical vectors: `handshake_valid.bin`, `ack_msgpack.bin`; no canonical
      MessagePack application-frame vector exists, so the harness constructs it.

37. **EC-037 — Oversized declared frame is rejected before read or allocation**
    - Class: **Baseline**.
    - Precondition: Establish a session, enable allocation/read probes, and do
      not provide any bytes after the six-byte vector header.
    - Action: Send `frame_oversized.bin`.
    - Expected: The engine immediately reports
      `ERR_PAYLOAD_TOO_LARGE (413)`, safely writes `control_error.bin`, and
      closes. It neither requests payload bytes nor allocates a buffer based on
      the declared 16 MiB-plus-one length; observed memory does not grow by that
      declared size.
    - Canonical vectors: `frame_oversized.bin`, `control_error.bin`.

38. **EC-038 — Reserved and inconsistent flag bits are rejected**
    - Class: **Baseline**.
    - Precondition: Establish a session and derive frames from a valid Command
      header.
    - Action: Send one frame with each reserved flag bit and one with
      `FLAG_LAST_FRAG` but no `FLAG_FRAGMENT`.
    - Expected: Every case reports `ERR_PROTOCOL_VIOLATION (403)`, emits no
      application message, sends a safe Control error, and closes only the
      affected session.
    - Canonical vectors: `frame_channel_command.bin` as the base packet; flags
      are changed by the harness.

39. **EC-039 — Unknown channels and direction violations are rejected**
    - Class: **Baseline**.
    - Precondition: Establish a session.
    - Action: Send an unknown channel and an engine-to-client-only Log frame
      from the peer.
    - Expected: Each is `ERR_PROTOCOL_VIOLATION (403)`, is never delivered to
      the application, produces a safe Control error, and closes the affected
      session.
    - Canonical vectors: `frame_channel_command.bin` as the base packet; the
      channel byte is changed by the harness.

40. **EC-040 — Short prefixes and malformed application payloads are fatal**
    - Class: **Baseline**.
    - Precondition: Prepare a fragmented frame whose declared payload is
      shorter than its required four-byte prefix, plus invalid JSON and invalid
      MessagePack payloads.
    - Action: Send each case in a separately established compatible session.
    - Expected: Every structural or codec failure reports
      `ERR_PROTOCOL_VIOLATION (403)`, produces no message event or
      success-shaped payload, sends a Control error when safe, and closes.
    - Canonical vectors: `frame_fragment_first.bin` as the base packet;
      malformed cases are constructed by the harness.

41. **EC-041 — Uncorrelated fragments reassemble once in stream order**
    - Class: **Baseline**.
    - Precondition: Establish a session and record message events.
    - Action: Send `frame_fragment_first.bin` followed by
      `frame_fragment_last.bin`.
    - Expected: No event occurs after the first frame. The second produces
      exactly one message with `Hello World`, the original channel, and no
      correlation value; the completed buffer is released.
    - Canonical vectors: `frame_fragment_first.bin`,
      `frame_fragment_last.bin`.

42. **EC-042 — Reassembled data cannot exceed 16 MiB**
    - Class: **Baseline**.
    - Precondition: Establish a session and start a fragment sequence whose
      cumulative data is just below 16 MiB.
    - Action: Send a final otherwise valid fragment that would make message data
      16 MiB plus one byte.
    - Expected: The cumulative size is checked before extending the buffer. The
      engine reports `ERR_PAYLOAD_TOO_LARGE (413)`, never allocates the
      over-limit result, sends a safe Control error, discards the sequence, and
      closes.
    - Canonical vectors: `frame_fragment_first.bin` as the layout oracle; the
      harness constructs boundary-sized fragments.

43. **EC-043 — Incomplete reassembly expires**
    - Class: **Baseline**.
    - Precondition: Configure a short positive fragment timeout and establish a
      session.
    - Action: Send `frame_fragment_first.bin`, send no final fragment, and
      advance the harness clock or wait within the bounded test deadline.
    - Expected: The engine emits `ERR_FRAGMENT_TIMEOUT (404)`, discards the
      incomplete sequence, and never dispatches it. A later sequence can reuse
      the released identifier without receiving old data.
    - Canonical vectors: `frame_fragment_first.bin`.

44. **EC-044 — Active fragment-sequence limit is enforced per session**
    - Class: **Baseline**.
    - Precondition: Configure active-sequence limit `1` and establish two
      sessions.
    - Action: Start one permitted Command sequence, then attempt a Data sequence
      in the same session while also starting an equal identifier in the other
      session.
    - Expected: The second same-session sequence reports
      `ERR_PROTOCOL_VIOLATION (403)`, is not buffered, and closes after a safe
      Control error. The other session's independent sequence is accepted,
      proving that the cap is per session.
    - Canonical vectors: `frame_fragment_first.bin` as the base layout; IDs and
      channels are changed by the harness.

45. **EC-045 — Fragment consistency and non-interleaving are enforced**
    - Class: **`CAP_CORRELATION`**.
    - Precondition: Establish a correlation-enabled session.
    - Action: In separate runs, change the correlation flag or ID inside one
      active sequence, start a conflicting sequence with its active fragment ID
      and different prefix state, send a correlated frame with a short prefix,
      and interleave a second fragment sequence on the same channel.
    - Expected: Every inconsistent or interleaved run reports
      `ERR_PROTOCOL_VIOLATION (403)`, dispatches no partial message, discards the
      affected state, sends a safe Control error, and closes.
    - Canonical vectors: `frame_fragment_correlated_first.bin`,
      `frame_fragment_correlated_last.bin` as base packets; inconsistent fields
      are changed by the harness.

---

## 7. Control protocol and liveness

46. **EC-046 — Heartbeat is always JSON and resets liveness**
    - Class: **Baseline**.
    - Precondition: Establish a MessagePack application session with a liveness
      counter one miss short of timeout.
    - Action: Send `control_heartbeat.bin`.
    - Expected: The engine parses the Control payload as UTF-8 JSON regardless
      of MessagePack negotiation, resets only that session's liveness counter,
      emits no application message, and keeps the session open.
    - Canonical vectors: `control_heartbeat.bin`.

47. **EC-047 — Heartbeat emission and timeout are session-local**
    - Class: **Baseline**.
    - Precondition: Enable a short positive heartbeat interval and miss limit
      and establish two sessions.
    - Action: Keep one peer active with valid frames and leave the other silent
      past the configured threshold.
    - Expected: Engine heartbeat frames are valid JSON Control frames with UTC
      millisecond timestamps. Any valid frame resets only its receiving
      session. Only the silent session disconnects, exactly once, with heartbeat
      timeout reason.
    - Canonical vectors: `control_heartbeat.bin` as the output shape oracle.

48. **EC-048 — Ping receives a pong with the same sequence**
    - Class: **Baseline**.
    - Precondition: Establish a session and use a heartbeat timeout longer than
      the harness deadline.
    - Action: Send `control_ping.bin`.
    - Expected: The engine returns a Control pong semantically equivalent to
      `control_pong.bin` within the configured timeout. The `seq` value is
      unchanged, no application event is emitted, and the session remains open.
    - Canonical vectors: `control_ping.bin`, `control_pong.bin`.

49. **EC-049 — Fatal post-session error is sent before close**
    - Class: **Baseline**.
    - Precondition: Establish a session and trigger a safely frameable
      payload-size violation.
    - Action: Send `frame_oversized.bin` and capture all engine output through
      EOF.
    - Expected: The final complete frame before EOF is a JSON Control error
      equivalent to `control_error.bin` with code `413`. The engine closes
      immediately afterward, sends no later frame, reports the terminal error
      once, and emits one protocol-failure disconnect.
    - Canonical vectors: `frame_oversized.bin`, `control_error.bin`.

50. **EC-050 — Unknown valid Control types are ignored silently**
    - Class: **Baseline**.
    - Precondition: Establish a session and construct a valid UTF-8 JSON Control
      object with an unrecognized string `type`.
    - Action: Send the frame, then send a valid application frame.
    - Expected: The unknown Control object causes no response, application
      event, error event, protocol or application state mutation beyond the
      normal liveness reset, or close. The following valid application frame is
      dispatched normally.
    - Canonical vectors: `control_heartbeat.bin` as the frame-layout base and
      `frame_channel_command.bin` for the follow-up.

51. **EC-051 — Malformed Control and received fatal error obey terminal rules**
    - Class: **Baseline**.
    - Precondition: Prepare sessions for malformed Control JSON, a valid JSON
      Control object with a missing or non-string `type`, and a received
      `control_error.bin`.
    - Action: Send each input and attempt further application output after the
      peer error.
    - Expected: Malformed JSON and invalid `type` structure are
      `ERR_PROTOCOL_VIOLATION (403)`, not unknown types, and close after a safe
      Control error. After receiving `control_error.bin`, the engine surfaces
      code `413`, sends no more frames, and tears down the session without
      converting the cause to a normal disconnect.
    - Canonical vectors: `control_error.bin`; malformed Control is constructed
      from the `control_heartbeat.bin` layout.

---

## 8. Correlation

52. **EC-052 — Correlated input without negotiation is rejected**
    - Class: **Baseline**.
    - Precondition: Establish a session whose ACK has no
      `CAP_CORRELATION`.
    - Action: Send `frame_correlated_not_negotiated.bin`.
    - Expected: The engine reports `ERR_PROTOCOL_VIOLATION (403)`, sends a safe
      Control error, closes only this session, and emits no application message.
    - Canonical vectors: `ack_capabilities_none.bin`,
      `frame_correlated_not_negotiated.bin`.

53. **EC-053 — A response repeats the request correlation ID**
    - Class: **`CAP_CORRELATION`**.
    - Precondition: Establish a JSON correlation-enabled session and configure
      the application callback to answer the test request with `{"ok":true}`.
    - Action: Send `frame_correlated_request.bin` and capture the response.
    - Expected: The message event exposes correlation ID `42`. The response is
      wire-equivalent to `frame_correlated_response.bin`: it sets
      `FLAG_CORRELATED`, prefixes Big-Endian ID `42`, decodes to `{"ok":true}`,
      and addresses only the requesting session.
    - Canonical vectors: `handshake_cap_correlation.bin`,
      `ack_cap_correlation.bin`, `frame_correlated_request.bin`,
      `frame_correlated_response.bin`.

54. **EC-054 — An application error repeats the request correlation ID**
    - Class: **`CAP_CORRELATION`**.
    - Precondition: Establish a JSON correlation-enabled session and configure
      the application to return a valid application-level error payload.
    - Action: Send `frame_correlated_request.bin`.
    - Expected: The response uses the Data channel, sets `FLAG_CORRELATED`, and
      repeats correlation ID `42` before the encoded application error. It does
      not use a protocol Control error and does not close the session.
    - Canonical vectors: `frame_correlated_request.bin`; the application error
      response is constructed by the harness.

55. **EC-055 — Fragment and correlation prefixes retain fixed order**
    - Class: **`CAP_CORRELATION`**.
    - Precondition: Establish a correlation-enabled session.
    - Action: Send `frame_fragment_correlated_first.bin` followed by
      `frame_fragment_correlated_last.bin`.
    - Expected: The engine decodes `fragment_id` before `correlation_id` in
      every frame, verifies repeated IDs, emits nothing after the first frame,
      then dispatches exactly `Hello World` with correlation ID `42`.
    - Canonical vectors: `frame_fragment_correlated_first.bin`,
      `frame_fragment_correlated_last.bin`.

56. **EC-056 — Pending correlation identifiers have a bounded lifecycle**
    - Class: **`CAP_CORRELATION`**.
    - Precondition: Establish a correlation-enabled session and create one
      pending engine-originated request where the SDK's idiomatic API supports
      such requests; otherwise exercise the same pending-state path through the
      SDK's internal protocol testkit.
    - Action: Attempt to reuse its ID while pending, complete or time out the
      request, reuse the released ID, then inject a late unmatched response.
    - Expected: Reuse while pending fails. Completion or timeout releases the
      ID. A late unmatched response is never delivered as the response to the
      newer request, and no pending state crosses a session boundary.
    - Canonical vectors: `frame_correlated_response.bin` as the response layout
      oracle; lifecycle traffic is constructed by the harness.

---

## 9. Engine API sends, errors, and public boundary

57. **EC-057 — Uncorrelated sends use the selected encoding and preserve order**
    - Class: **Baseline**.
    - Precondition: Establish JSON and MessagePack sessions and retain their
      live handles.
    - Action: Submit two sequential uncorrelated Data sends and one Log send per
      session.
    - Expected: Each send reaches exactly its target session, has no correlation
      prefix, uses that session's immutable negotiated encoding, and uses only
      valid engine-output channels. The two sequential Data sends arrive in
      submission order.
    - Canonical vectors: none; output frames contain harness-selected payloads.

58. **EC-058 — Correlated send is gated and preserves the supplied ID**
    - Class: **`CAP_CORRELATION`**.
    - Precondition: Keep one correlation-enabled and one baseline session live.
    - Action: Send the same correlated Data payload with ID `42` through each
      handle.
    - Expected: The enabled session receives a frame equivalent to
      `frame_correlated_response.bin`. The baseline send fails explicitly
      before writing. Neither outcome affects the other session.
    - Canonical vectors: `frame_correlated_response.bin`,
      `ack_capabilities_none.bin`.

59. **EC-059 — Applications cannot forge Control or violate directions**
    - Class: **Baseline**.
    - Precondition: Establish a live session.
    - Action: Through the public send surface, attempt Control session,
      heartbeat, ping/pong, and protocol-error messages; a Command send; and an
      unknown channel send.
    - Expected: Every attempt fails explicitly before transport output. The
      public surface cannot forge SDK-owned Control traffic and accepts only
      engine-to-client application directions from the protocol channel table.
    - Canonical vectors: `control_session.bin`, `control_heartbeat.bin`,
      `control_ping.bin`, `control_pong.bin`, and `control_error.bin` are
      forbidden-output oracles.

60. **EC-060 — Invalid, closed, and stale session sends fail in isolation**
    - Class: **Baseline**.
    - Precondition: Keep one live session plus absent, closed, and stale-epoch
      handles.
    - Action: Attempt the same send through every handle.
    - Expected: Only the live handle succeeds. Every other call fails
      explicitly, writes no bytes to any session, and neither closes nor mutates
      the live session.
    - Canonical vectors: none.

61. **EC-061 — Serialization and size failures are explicit**
    - Class: **Baseline**.
    - Precondition: Establish a live session and prepare a payload the selected
      codec cannot serialize, a payload whose encoded frame exceeds 16 MiB, and
      a fragmented-message candidate whose data exceeds 16 MiB.
    - Action: Submit each payload through the public send operation.
    - Expected: Every call fails explicitly before invalid wire output or
      over-limit allocation. No empty payload, truncation, implicit alternate
      codec, or success result is substituted, and the session remains usable.
    - Canonical vectors: `frame_oversized.bin` as the size-boundary oracle.

62. **EC-062 — Deferred transport failure becomes one error event**
    - Class: **Baseline**.
    - Precondition: Configure the SDK so an accepted send is queued, then inject
      a transport write failure before completion.
    - Action: Submit the send and observe its result and events.
    - Expected: If initial acceptance succeeds, the later failure is surfaced
      exactly once through an error event containing category, applicable
      status, write phase, cause, and the correct session handle. It is never
      converted to a successful message or normal disconnect reason and does
      not close unrelated sessions.
    - Canonical vectors: none.

63. **EC-063 — Error events preserve phase, handle, and terminal cause**
    - Class: **Baseline**.
    - Precondition: Prepare invalid configuration, endpoint acquisition,
      pre-session handshake, established-session protocol, and terminal
      transport failures.
    - Action: Trigger each failure separately and record results and events.
    - Expected: Configuration/endpoint/pre-session failures have no session
      handle; established-session failures carry the final handle. Applicable
      protocol status, phase, category, and cause are preserved. Each terminal
      cause is reported once and is never replaced with empty data, success, or
      a generic normal-disconnect result.
    - Canonical vectors: `handshake_bad_magic.bin`, `frame_oversized.bin`,
      `control_error.bin`.

64. **EC-064 — Public API remains engine-only and documents event execution**
    - Class: **Baseline**.
    - Precondition: Build the SDK's public-package surface and documentation as
      a normal consumer.
    - Action: Run the SDK's API-surface conformance check and documentation
      assertions.
    - Expected: The required engine operations and connected, message, error,
      and disconnected events are publicly consumable through idiomatic
      constructs. The event execution context and concurrent-call ordering are
      documented. No public outbound client/dialer API, mandatory process
      launcher, `Runner` equivalent, restart policy, or application semantics
      are required or exposed as part of the Engine API contract.
    - Canonical vectors: none.

---

## 10. Normative coverage

This table is the maintenance index for the acceptance criterion that every
Engine API rule has an executable test.

| Contract area | Tests |
|---|---|
| Engine configuration and defaults | EC-001, EC-004, EC-005 |
| Address derivation and platform transport | EC-002, EC-003, EC-009 |
| Endpoint liveness, stale cleanup, and close | EC-005 through EC-010 |
| Security and token handling | EC-001 through EC-003, EC-008, EC-009, EC-011 |
| Engine-side handshake and ACK | EC-012 through EC-023 |
| Capacity and concurrent sessions | EC-004, EC-024, EC-025 |
| Session identity, state, epoch, and isolation | EC-026 through EC-030 |
| Event ordering and payload contracts | EC-031 through EC-034, EC-063, EC-064 |
| Frame validation and payload bounds | EC-034 through EC-042 |
| Fragmentation | EC-028, EC-029, EC-041 through EC-045, EC-055 |
| Control, heartbeat, ping/pong, and fatal errors | EC-046 through EC-051 |
| Correlation negotiation and behaviour | EC-020 through EC-022, EC-028, EC-052 through EC-056, EC-058 |
| Engine application sends | EC-053, EC-054, EC-057 through EC-062 |
| Error observability and failure isolation | EC-014 through EC-018, EC-023, EC-032, EC-033, EC-037 through EC-040, EC-049, EC-051, EC-052, EC-060 through EC-063 |
| Engine-only public API boundary | EC-011, EC-059, EC-064 |

When a normative contract change is proposed, its specification change, vector
change where wire bytes are involved, and corresponding suite change must land
together. SDK-specific test implementations remain in their own repositories.
