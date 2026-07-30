# Yuumi Engine Conformance Suite

Status: **alpha**

Wire protocol: **version `1`**

This document is the single acceptance suite for the C++, Python, Rust, and
TypeScript engine SDKs. Every test is mandatory on Windows, Linux, and macOS
unless an assertion names one platform. The suite verifies observable
behaviour, not identical public spelling or internal architecture.

The normative sources are [`PROTOCOL.md`](./PROTOCOL.md) and
[`ENGINE_API.md`](./ENGINE_API.md). If this suite disagrees with either, the
contract wins and the suite must be corrected.

---

## 1. Applicability and harness

Tests are either **Baseline** or **`CAP_CORRELATION`**. Protocol version 1
engines must implement correlation, so capability cases cannot be skipped when
the engine advertises it.

The harness provides a private Go-role listener and can:

- open and protect the platform endpoint before an engine dials;
- accept one candidate and send exact handshake bytes, including split writes;
- read exact ACK, Control, and application bytes and detect EOF or timeout;
- inspect whether the engine created, removed, or changed endpoint state;
- inject dial, read, ACK-write, session-write, established-read/write, and
  close failures through test-only seams;
- record connected, message, heartbeat, error, and disconnected events and
  their start order;
- observe attempted reads and allocations at decoder boundaries; and
- control positive heartbeat and fragment deadlines without unbounded sleeps.

The harness is test infrastructure, not public non-Go client API. Each `.bin`
fixture is consumed byte-for-byte and its `.json` companion is the oracle.

Task 01 changes transport ownership and address derivation only. No existing
version 1 handshake, ACK, Control, or frame vector changes bytes. Task 02 adds
address fixtures for the minimum-name, maximum-name, 103-byte macOS boundary,
and 104-byte rejection examples and confirms every current `.bin` unchanged.

---

## 2. Configuration, address, dial, and public boundary

1. **EC-001 — Invalid configuration performs no transport operation**
   - Class: **Baseline**.
   - Invalid name, token, encoding/capability, PID, heartbeat, fragment, and
     overlong Unix path configurations fail before address use or dial. No
     success-shaped result or event is emitted.

2. **EC-002 — Canonical address examples reproduce byte for byte**
   - Class: **Baseline**.
   - The engine reproduces the documented minimum and maximum SHA-256 prefixes,
     Unix filenames, and Windows pipe names without case folding, rewriting,
     relocation, or token disclosure in the Unix pathname.

3. **EC-003 — macOS length is validated in bytes**
   - Class: **Baseline**.
   - The documented 59-byte temporary directory yields 103 bytes and reaches
     dial. Adding one `b` yields 104 bytes and fails before dial.

4. **EC-004 — Every engine is a platform-native dialer**
   - Class: **Baseline**.
   - Linux/macOS dial the exact Unix domain stream socket. Windows dials the
     exact byte-stream Named Pipe. No TCP, network, or cross-transport fallback
     is attempted.

5. **EC-005 — Engines never own endpoint lifecycle**
   - Class: **Baseline**.
   - With live, absent, stale-node, and access-denied endpoints, the engine
     neither probes for ownership nor binds, listens, unlinks, replaces,
     changes permissions/ACL, or cleans up. It only dials and reports failure.

6. **EC-006 — Refusal and busy states are explicit**
   - Class: **Baseline**.
   - An absent/refused listener fails the current connect attempt without
     hidden retry. A busy Windows pipe is treated as a live transport condition,
     never as authority to recreate it. A later application-initiated connect
     may succeed after Go is ready.

7. **EC-007 — Token selects a different address**
   - Class: **Baseline**.
   - Token B with the same name never reaches the listener created for token A.
     The engine does not emulate the token as a handshake field.

8. **EC-008 — Public API is dial-only and engine-only**
   - Class: **Baseline**.
   - The public surface provides connect, close, send, events, and state. It has
     no listener/open-server/accept surface, arbitrary path bypass, public
     client, mandatory Runner, or lifecycle policy. Event execution and
     concurrent send ordering are documented.

---

## 3. Received handshake and establishment

9. **EC-009 — Engine receives exactly 16 bytes before parsing**
   - Class: **Baseline**.
   - After dial, every non-empty prefix shorter than `handshake_valid.bin` and
     an empty close produce no ACK, Control, connected, or disconnected event.
     One typed candidate error identifies the read/transport phase.

10. **EC-010 — Valid JSON handshake produces exact output**
    - Class: **Baseline**.
    - Receiving `handshake_valid.bin` with JSON first produces exactly
      `ack_json.bin`, then one valid session Control frame, then connected.
      Nothing precedes ACK or appears between ACK and session assignment.

11. **EC-011 — Valid MessagePack handshake produces exact output**
    - Class: **Baseline**.
    - MessagePack-first preference produces `ack_msgpack.bin`; session
      assignment follows before application or heartbeat traffic.

12. **EC-012 — Bad magic and version close without output**
    - Class: **Baseline**.
    - `handshake_bad_magic.bin` reports `400`; `handshake_bad_version.bin`
      reports `401`. Both write zero bytes and emit no session event. Library
      semver does not affect the version decision.

13. **EC-013 — Empty encoding intersection closes without ACK**
    - Class: **Baseline**.
    - A JSON-only engine receiving `handshake_encoding_unsupported.bin` reports
      `415`, writes zero bytes, and emits no session event.

14. **EC-014 — PID checks preserve their limited role**
    - Class: **Baseline**.
    - Absent `expected_pid`, explicit zero, mismatch, and trustworthy server-
      credential mismatch remain distinct. Mismatch reports `402` and closes
      without ACK. Token and Go-owned OS access controls remain baseline.

15. **EC-015 — Encoding and capability selection are deterministic**
    - Class: **Baseline**.
    - Preference order selects one advertised known encoding. Reserved encoding
      bits are never selected. `handshake_cap_correlation.bin` yields either
      exact `ack_cap_correlation.bin` or `ack_capabilities_none.bin` according
      to intersection; unknown capability bits are excluded, not fatal.

16. **EC-016 — Establishment write failures create no session**
    - Class: **Baseline**.
    - Injected partial/failed ACK and post-ACK session write failures close,
      report one phased cause, and emit neither connected nor disconnected.

17. **EC-017 — Session assignment is valid and ordered**
    - Class: **Baseline**.
    - The assigned ID is non-empty printable ASCII of at most 128 bytes and is
      sent exactly once immediately after ACK. `control_session_empty_id.bin`
      is the invalid boundary oracle; connected begins only after the valid
      assignment is written.

---

## 4. One-to-one session, epoch, events, and close

18. **EC-018 — One engine instance has one session**
    - Class: **Baseline**.
    - A second connect while connecting or established fails explicitly and
      cannot affect the active session. There is no `max_sessions` option. A
      new connect is permitted only after complete teardown.

19. **EC-019 — Replacement performs full negotiation with empty state**
    - Class: **Baseline**.
    - After a partial fragment and disconnect, the next application-initiated
      connect receives a new handshake, emits a new session ID, replaces its
      opaque epoch, and begins with empty heartbeat, fragment, and correlation
      state. Epoch never appears on the wire.

20. **EC-020 — Stale work cannot address a replacement**
    - Class: **Baseline**.
    - Old responders, sends, callbacks, timeouts, fragments, and correlations
      fail or are discarded. They produce no bytes/events and cannot mutate or
      close the replacement.

21. **EC-021 — Event order is stable and non-blocking**
    - Class: **Baseline**.
    - Start order is connected, zero or more message/error events, disconnected.
      Application events are serial. A barrier-blocked handler does not stop
      transport I/O, heartbeat, timeout, or close.

22. **EC-022 — Disconnect is exact and reasoned**
    - Class: **Baseline**.
    - Local close, Go close, heartbeat timeout, protocol failure, and transport
      failure each produce exactly one matching disconnected event after a
      connected event. Candidate rejection produces none. No callback for that
      epoch begins afterward.

23. **EC-023 — Repeated close releases engine-owned resources only**
    - Class: **Baseline**.
    - Close stops dispatch and transport work and is idempotent. It does not
      unlink, release, or modify the Go-owned endpoint, which remains able to
      admit another engine candidate.

---

## 5. Frames, fragmentation, and Control

24. **EC-024 — Complete JSON and MessagePack input dispatches once**
    - Class: **Baseline**.
    - `frame_channel_command.bin` dispatches one JSON Command. A harness-built
      valid MessagePack Command dispatches once under MessagePack and is not
      parsed as JSON. Control and partial fragments never reach the application.

25. **EC-025 — Declared oversize is rejected before read/allocation**
    - Class: **Baseline**.
    - `frame_oversized.bin` immediately reports `413`, safely writes
      `control_error.bin`, and closes without reading or allocating the declared
      16 MiB-plus-one payload.

26. **EC-026 — Structural failures remain `403`**
    - Class: **Baseline**.
    - Reserved flags, LAST without FRAGMENT, unknown/wrong-direction channels,
      short prefixes, malformed JSON/MessagePack, and inconsistent fragment
      prefixes emit no message, safely report `403`, and close.

27. **EC-027 — Fragmentation vectors reassemble unchanged**
    - Class: **Baseline**.
    - `frame_fragment_first.bin` followed by `frame_fragment_last.bin` emits
      exactly `Hello World` once. Cumulative 16 MiB-plus-one is checked before
      buffer extension and reports `413`.

28. **EC-028 — Fragment lifetime and capacity are bounded**
    - Class: **Baseline**.
    - Incomplete sequences expire with `404`; active-sequence cap and same-
      channel non-interleaving are enforced; completed/expired state is freed.
      No fragment state survives a reconnect.

29. **EC-029 — Heartbeat is JSON and session-local**
    - Class: **Baseline**.
    - `control_heartbeat.bin` parses as JSON even under MessagePack, resets
      liveness, emits no application event, and keeps the session open. Silence
      triggers exactly one heartbeat-timeout disconnect.

30. **EC-030 — Ping/pong and fatal Control ordering are unchanged**
    - Class: **Baseline**.
    - `control_ping.bin` receives a semantic `control_pong.bin` with unchanged
      sequence. A safely frameable fatal error writes `control_error.bin` as the
      last complete frame before EOF.

31. **EC-031 — Unknown and malformed Control remain distinct**
    - Class: **Baseline**.
    - Unknown valid types are ignored except normal liveness reset. Malformed
      JSON or missing/non-string `type` reports `403` and closes. Receiving a
      fatal Control error preserves its code and forbids later output.

---

## 6. Correlation and public sends

32. **EC-032 — Correlation is capability-gated**
    - Class: **Baseline** and **`CAP_CORRELATION`**.
    - `frame_correlated_not_negotiated.bin` reports `403`. With negotiated
      correlation, `frame_correlated_request.bin` exposes ID `42` and an answer
      is wire-equivalent to `frame_correlated_response.bin`.

33. **EC-033 — Application errors preserve correlation**
    - Class: **`CAP_CORRELATION`**.
    - An application error response uses Data, repeats ID `42`, does not use a
      protocol Control error, and does not close.

34. **EC-034 — Combined prefix order is unchanged**
    - Class: **`CAP_CORRELATION`**.
    - `frame_fragment_correlated_first.bin` and
      `frame_fragment_correlated_last.bin` decode fragment ID before repeated
      correlation ID and emit `Hello World` once with ID `42`.

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

44. **EC-044 — Active fragment-sequence limit is enforced per epoch**
    - Class: **Baseline**.
    - Precondition: Configure active-sequence limit `1` and establish a session.
    - Action: Start one permitted Command sequence, then attempt a Data sequence
      in the same session. Disconnect, reconnect, and start an equal identifier
      in the replacement.
    - Expected: The second same-session sequence reports
      `ERR_PROTOCOL_VIOLATION (403)`, is not buffered, and closes after a safe
      Control error. The replacement's equal identifier is accepted, proving
      the cap and buffers do not cross epochs.
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

47. **EC-047 — Heartbeat emission and timeout are epoch-local**
    - Class: **Baseline**.
    - Precondition: Enable a short positive heartbeat interval and miss limit
      and establish a session.
    - Action: Keep it active with valid frames, disconnect, then establish a
      replacement and leave it silent past the configured threshold.
    - Expected: Engine heartbeat frames are valid JSON Control frames with UTC
      millisecond timestamps. Activity resets only the current epoch. Only the
      silent replacement disconnects, exactly once, with heartbeat timeout.
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

57. **EC-057 — Uncorrelated sends use selected encoding and preserve order**
    - Class: **Baseline**.
    - Precondition: Establish a JSON session, close it, then establish a
      MessagePack replacement.
    - Action: Submit two sequential uncorrelated Data sends and one Log send in
      each session.
    - Expected: Every send has no correlation prefix, uses its session's
      immutable negotiated encoding, and uses only valid engine-output channels.
      Sequential Data sends arrive in submission order and no queued send
      crosses the disconnect.
    - Canonical vectors: none; output frames contain harness-selected payloads.

58. **EC-058 — Correlated send is gated and preserves supplied ID**
    - Class: **`CAP_CORRELATION`**.
    - Precondition: Establish a correlation-enabled session, close it, then a
      baseline replacement.
    - Action: Send the same correlated Data payload with ID `42` in each.
    - Expected: The enabled session receives a frame equivalent to
      `frame_correlated_response.bin`. The baseline send fails before writing.
      Neither outcome crosses the epoch boundary.
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

60. **EC-060 — Absent, closed, and stale-epoch sends fail in isolation**
    - Class: **Baseline**.
    - Precondition: Keep one live session plus absent, closed, and stale-epoch
      views or responders.
    - Action: Attempt the same send through every state.
    - Expected: Only current live-epoch work succeeds. Every other call fails,
      writes no bytes, and neither closes nor mutates the live session.
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
    - Precondition: Configure an implementation whose send operation internally
      queues a write, then inject transport failure before write completion.
    - Action: Submit and await the send result and observe events.
    - Expected: The send does not complete successfully before the write. It
      fails, and the terminal transport cause is surfaced exactly once with
      category, status where applicable, write phase, cause, and current epoch.
      It is not converted to success or a normal disconnect and cannot mutate
      the Go listener or a replacement session.
    - Canonical vectors: none.

63. **EC-063 — Error events preserve phase, handle, and terminal cause**
    - Class: **Baseline**.
    - Precondition: Prepare invalid configuration, address derivation, dial,
      candidate handshake, established-session protocol, and terminal
      transport failures.
    - Action: Trigger each failure separately and record results and events.
    - Expected: Configuration/address/dial/candidate failures have no session
      epoch; established-session failures carry the final epoch. Applicable
      protocol status, phase, category, and cause are preserved. Each terminal
      cause is reported once and is never replaced with empty data, success,
      or a generic normal-disconnect result.
    - Canonical vectors: `handshake_bad_magic.bin`, `frame_oversized.bin`,
      `control_error.bin`.

64. **EC-064 — Public API remains engine-only and documents event execution**
    - Class: **Baseline**.
    - Precondition: Build the SDK's public-package surface and documentation as
      a normal consumer.
    - Action: Run the SDK's API-surface conformance check and documentation
      assertions.
    - Expected: The required engine operations and connected, message,
      heartbeat, error, and disconnected events are publicly consumable through idiomatic
      constructs. The event execution context and concurrent-call ordering are
      documented. No public listener/server or client API, mandatory process
      launcher, `Runner` equivalent, restart policy, or application semantics
      are required or exposed as part of the Engine API contract.
    - Canonical vectors: none.

---

## 10. Task 03 state, dispatch, and runtime cases

65. **EC-065 — Environment adapter is configuration-only**
    - Reading valid `YUUMI_ENDPOINT_NAME` and `YUUMI_TOKEN` returns config;
      missing/invalid values are typed configuration errors. No dial, listener,
      process, retry, discovery, or supervision work occurs.

66. **EC-066 — Connect uses an immutable configuration snapshot**
    - Mutating caller-owned configuration during dial/handshake cannot alter
      address, preferences, capabilities, timeouts, or queue capacity for that
      attempt. Invalid configuration fails before dial.

67. **EC-067 — Terminal result survives event-delivery failure**
    - Transport, protocol, backpressure, and callback terminal causes remain
      observable with kind, phase, cause, and epoch even when an event observer
      itself fails. No disconnected success replaces the cause.

68. **EC-068 — Exact state machine and epoch monotonicity**
    - Observe idle/connecting/connected/closing/idle. Duplicate connect reports
      already-connecting/already-connected without interference. Close cancels
      connect, idle close is safe, reconnect requires a new call, and each
      successful epoch is nonzero and strictly greater than its predecessor.

69. **EC-069 — Application queue capacity is exact**
    - Default capacity accepts 64 pending application events and configured N
      accepts N. Two terminal slots do not increase application capacity.

70. **EC-070 — Backpressure terminates without hidden loss**
    - Entry N+1 stops application acceptance without blocking IPC indefinitely,
      closes only that epoch, drains accepted events in order, then delivers the
      reserved backpressure error and disconnected event. No event is dropped
      while the session continues.

71. **EC-071 — Callback failures are observable**
    - Throw/reject/panic from a message or lifecycle handler becomes one
      `application` error and never success. Error-observer failure reaches the
      runtime-native uncaught facility once and is not recursively dispatched.

72. **EC-072 — TypeScript dispatch yields to IPC work**
    - Below queue capacity, callbacks execute on distinct event-loop turns and
      parsing, heartbeat, timeout, and close advance between them. The docs
      identify synchronous CPU-bound application work as the remaining limit.

73. **EC-073 — Required error kinds are distinguishable**
    - Every `ENG-ERR-*` condition can be produced and distinguished through the
      idiomatic result/error type, including phase, cause, optional epoch, and
      applicable protocol status, without a success-shaped fallback.

---

## 11. Normative coverage

| Contract area | Tests |
|---|---|
| Configuration and canonical address | EC-001 through EC-003, EC-066 |
| Dial-only transport and endpoint non-ownership | EC-004 through EC-008 |
| Received handshake, ACK, and session assignment | EC-009 through EC-017 |
| One-to-one session, epoch, event order, and close | EC-018 through EC-023, EC-067 through EC-071 |
| Frame validation and payload bounds | EC-024 through EC-027, EC-035 through EC-042 |
| Fragmentation | EC-027, EC-028, EC-041 through EC-045, EC-055 |
| Control, heartbeat, ping/pong, and fatal errors | EC-029 through EC-031, EC-046 through EC-051 |
| Correlation negotiation and behaviour | EC-015, EC-032 through EC-035, EC-052 through EC-056, EC-058 |
| Engine application sends | EC-032 through EC-037, EC-053, EC-054, EC-057 through EC-062 |
| Dispatch, backpressure, and runtime constraints | EC-021, EC-022, EC-069 through EC-072 |
| Error observability | EC-009, EC-012 through EC-016, EC-022, EC-025, EC-026, EC-030, EC-031, EC-037 through EC-040, EC-049, EC-051, EC-052, EC-060 through EC-063, EC-067, EC-070, EC-071, EC-073 |
| Product and public boundary | EC-008, EC-038, EC-064, EC-065 |

When a normative contract change is proposed, its specification change, vector
change where wire bytes are involved, and corresponding suite change must land
together. Listener inversion changes no existing version 1 vector bytes.
