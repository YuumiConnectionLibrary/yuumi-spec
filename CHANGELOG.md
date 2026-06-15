# Changelog

## v2.final

Release type: protocol lock/freeze (non-breaking over v2 baseline).

### Added

1. **Control channel schema on `ChannelControl` (`0x00`)**
   - Fixed JSON schema for control messages:
     - `{ "type": "heartbeat", "ts": <unix_ms> }`
     - `{ "type": "error", "code": <int>, "message": <string> }`
     - `{ "type": "ping", "seq": <int> }`
     - `{ "type": "pong", "seq": <int> }`
   - Control channel encoding is always JSON, independent from negotiated data encoding.
   - Compliance rules:
     - Ping must be answered with pong within heartbeat timeout.
     - Protocol violations must send `error` before close.
     - Unknown control `type` values are silently ignored (forward compatibility).

2. **Frame fragmentation via `Flags` byte**
   - `FLAG_FRAGMENT` = `0x01` (bit 0)
   - `FLAG_LAST_FRAG` = `0x02` (bit 1)
   - Bits 2-7 reserved and must be `0x00`.
   - Fragmented payloads prefix `fragment_id` (`uint32`, Big-Endian) in first 4 payload bytes.
   - Reassembly defaults and guards:
     - Timeout configurable, default `15s`.
     - Max concurrent fragment buffers configurable, default `16`.
     - Exceeding cap closes with `ERR_PROTOCOL_VIOLATION (403)`.
     - `fragment_id` wrap (`u32`) handled incrementally.

3. **Configurable heartbeat defaults (SDK options, not wire-negotiated)**
   - `interval`: default `30s`
   - `miss_threshold`: default `3`
   - `enabled`: default `true`

4. **Security model and platform credential behavior**
   - Socket creation requirement: mode `0600` when supported.
   - PID strict mode:
     - `expected_pid != 0` rejects mismatched PID (close without ACK).
     - `expected_pid == 0` accepts any PID.
   - Platform credential notes:
     - Linux: `SO_PEERCRED` (`ucred`)
     - macOS: `LOCAL_PEERCRED` (`xucred`) + `proc_pidpath` fallback validation
     - Windows: AF_UNIX socket ACL trust model; handshake PID accepted as-is when ACLs are trusted

5. **Status code**
   - Added `ERR_PID_MISMATCH (402)`.

6. **Conformance test vectors**
   - Added canonical vector pairs (`.bin` + `.json`) in `test-vectors/`:
     - `frame_fragment_first`
     - `frame_fragment_last`
     - `control_heartbeat`
     - `control_error`
     - `control_ping`
     - `control_pong`

### Freeze policy

Protocol v2 is frozen. No breaking changes are allowed for 12 months from the
v2.final release date. Future protocol evolution in this window must be additive.
