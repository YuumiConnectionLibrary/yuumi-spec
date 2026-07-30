# Yuumi Client Conformance Suite

Status: **alpha**

Wire protocol: **version `1`**

This is the executable acceptance suite for the Go Client API. Every case is
mandatory on Windows, Linux, and macOS unless it names one platform. The
normative sources are [`PROTOCOL.md`](./PROTOCOL.md) and
[`CLIENT_API.md`](./CLIENT_API.md); the contract wins on disagreement.

---

## 1. Harness

The harness uses a private engine dialer, never a public non-Go client. It can
split reads/writes, send exact vectors, inspect endpoint protection, inject
transport failures, observe allocation attempts, block application handlers,
control deadlines without unbounded sleeps, and record state/event order.

Existing handshake, ACK, Control, and frame vectors remain byte-identical.
API-only cases below require no new wire fixtures.

---

## 2. Construction, configuration, address, and endpoint

1. **CC-001 — Invalid configuration has no side effects**
   - Invalid required fields, negative options, reserved capabilities, and an
     overlong Unix path fail in `NewClient` before probe, bind, unlink, handle,
     goroutine, or timer creation.

2. **CC-002 — Canonical address is byte-identical**
   - Minimum/maximum fixtures reproduce documented Unix digests and Windows
     pipe names without normalization, truncation, relocation, or fallback.

3. **CC-003 — macOS byte budget is exact**
   - The 103-byte fixture reaches `Open`; 104 bytes fails before endpoint use.

4. **CC-004 — Open protects the platform listener before traffic**
   - Unix uses stream socket mode `0600`; Windows uses a byte-stream Named Pipe,
     intended-user ACL, remote rejection, and `Microsoft/go-winio`. `Open`
     returns ready without waiting for an engine. TCP never appears.

5. **CC-005 — Live endpoint is never replaced**
   - A second client's `Open` reports `endpoint_live` and leaves the first
     listener usable. A busy Named Pipe is live, not stale.

6. **CC-006 — Stale cleanup requires proved refusal**
   - Unix unlink happens only after refused liveness probe; Windows releases
     handles and performs no filesystem unlink. Unrelated paths are unchanged.

7. **CC-007 — Close deterministically releases ownership**
   - From listening/connected, repeated `Close` releases candidates, session,
     endpoint, timers, goroutines, queues, and waits. The address can be owned
     by a new object, while the closed object cannot reopen.

---

## 3. Admission and establishment

8. **CC-008 — Go sends exact handshake after secure accept**
   - A dialer receives no pre-accept traffic, then exact
     `handshake_valid.bin` or `handshake_cap_correlation.bin` including Go PID.

9. **CC-009 — ACK and assignment establish one session**
   - Exact ACK followed immediately by `control_session.bin` makes
     `WaitConnected` and `OnConnected` observe the same immutable ready view.

10. **CC-010 — Invalid candidates do not consume the slot**
    - Short/invalid ACK, unoffered selection/capability, peer failure, and
      `control_session_empty_id.bin` close only the candidate, emit typed
      diagnostics without epoch, and admission later establishes a valid peer.

11. **CC-011 — One established session is mandatory**
    - A later dialer is refused/closed without handshake and cannot affect the
      active epoch. After teardown, one new candidate may establish.

12. **CC-012 — Wait cancellation differs from listener failure**
    - Canceling one `WaitConnected` leaves client/admission usable. `Close`
      wakes every waiter with `closed`; fatal accept failure closes the object
      with `accept`, not an engine-disconnect success.

13. **CC-013 — Optional PID remains an additional check**
    - Nil, pointer-to-zero, match, and trustworthy-credential mismatch are
      distinct. Mismatch reports `402`, sends no handshake, and leaves the slot.

---

## 4. Wire, operations, and epochs

14. **CC-014 — Version 1 vectors remain unchanged**
    - Negotiation, channels, Control JSON, correlation, fragmentation, payload
      bounds, heartbeat, ping/pong, and statuses pass every applicable fixture.

15. **CC-015 — Declared length is checked before allocation**
    - `frame_oversized.bin` reports `413`, safely sends `control_error.bin`, and
      closes without reading/allocating the declared body.

16. **CC-016 — Inbound paths never overlap**
    - Replies reach only `Request`, unsolicited complete messages only
      `Messages`, and Control only SDK state/callbacks. Partial or invalid input
      never becomes data or success.

17. **CC-017 — Sends are directional, ordered, and explicit**
    - Only Command/Data are public. Sequential successful sends preserve order
      and selected encoding. Control, wrong direction, serialization, and size
      failures write no invalid bytes.

18. **CC-018 — Requests are session-scoped**
    - Capability gating, concurrent unique IDs, timeout/context precedence, ID
      release, and late-reply discard are verified without routing overlap.

19. **CC-019 — Replacement resets generation state**
    - Disconnect fails requests, clears partial work, and returns to listening.
      The next handshake uses a new session ID and strictly greater local epoch.

20. **CC-020 — Stale work cannot act on replacement**
    - Old sends, responders, callbacks, timeouts, fragments, correlations, and
      queued operations emit/write nothing and cannot mutate or close new epoch.

21. **CC-021 — Public boundary has no lifecycle policy**
    - Surface inspection finds `NewClient`, `Open`, session operations, events,
      and close, but no required Runner, reconnect policy, spawn/discovery,
      executable/log capture, application envelope, or non-Go public client.

---

## 5. Task 03b API, state, dispatch, and error cases

22. **CC-022 — Construction is transport-free**
    - Successful `NewClient` creates no handle, endpoint, goroutine, timer, or
      callback and copies configuration so caller mutation has no effect.

23. **CC-023 — Optional zero values are normative**
    - Zero options produce heartbeat 30 s/3, request timeout 30 s, message and
      callback capacity 64, enabled heartbeat, and absent expected PID.

24. **CC-024 — GenerateToken and Decode boundaries are typed**
    - Generated tokens contain 128 secure random bits encoded as 32 lowercase
      hex; invalid Decode destinations and codec conversion failures are errors.

25. **CC-025 — Exact state machine and permanent close**
    - Observe new/listening/connected/listening and closing/closed transitions;
      failed `Open` cleans back to new, duplicate `Open` fails, and closed never
      reopens. Epoch starts above zero and increases on every establishment.

26. **CC-026 — Platform close has no leaks**
    - On each OS, close during accept, handshake, established reads/writes,
      callback wait, and heartbeat unblocks all work within bounded deadlines.

27. **CC-027 — Connected-state candidates are isolated**
    - Multiple extra dials receive no handshake/session and do not change
      callbacks, epoch, negotiated values, liveness, or the established stream.

28. **CC-028 — Disconnect and Close drain differently**
    - Disconnect preserves already accepted old-epoch events in order, fails
      requests with `session_closed`, emits disconnected, then permits next
      connected event. Close cancels work with `closed` and closes `Messages`.

29. **CC-029 — Every stale authority is isolated**
    - Independently exercise send, request completion, timer, fragment,
      correlation, queued event, and callback from an old epoch against a live
      replacement and observe no replacement effect.

30. **CC-030 — Queue capacity boundary is exact**
    - Default capacity accepts 64 pending entries and configured positive N
      accepts N for both Messages and callbacks; the next entry overflows.

31. **CC-031 — Backpressure is terminal and loss is not hidden**
    - Full message or callback queue never blocks IPC indefinitely and never
      drops then continues. It records `backpressure`, fails requests, closes
      that epoch, uses reserved terminal delivery, and returns to listening.

32. **CC-032 — Callback order, panic, locks, and close are safe**
    - Same-epoch callbacks do not overlap and follow connected/events/
      disconnected order. Public methods proceed while a callback is blocked.
      Panic becomes `application`; OnError panic reports once without recursion.
      Close from inside and outside a callback follows the documented rule.

33. **CC-033 — IPC progresses independently of handlers**
    - Below capacity, blocked handlers do not prevent reads, writes, heartbeat,
      fragment/request deadlines, candidate rejection, or close progress.

34. **CC-034 — Error kinds are distinguishable**
    - Construct every `CLI-ERR-*` condition and verify `errors.Is`/`errors.As`,
      phase, cause, optional epoch, single terminal report, and no success shape.

---

## 6. Normative coverage

| Contract requirements | Cases |
|---|---|
| `CLI-ROLE-*` | CC-004 through CC-007, CC-021, CC-022 |
| `CLI-API-*`, `CLI-CFG-*` | CC-001, CC-007 through CC-009, CC-016 through CC-018, CC-022 through CC-024 |
| `CLI-STATE-*` | CC-007, CC-009 through CC-012, CC-019, CC-020, CC-025 |
| `CLI-ENDP-*` | CC-001 through CC-007, CC-026 |
| `CLI-ADMIT-*` | CC-008 through CC-013, CC-027 |
| `CLI-SESS-*` | CC-014 through CC-020, CC-028, CC-029 |
| `CLI-DISP-*` | CC-016, CC-030 through CC-033 |
| `CLI-ERR-*` | CC-001, CC-005 through CC-020, CC-031, CC-032, CC-034 |

No case tests process lifecycle. No wire vector changes for Task 03b.
