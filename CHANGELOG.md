# Changelog

Protocol revisions are recorded as dated change entries. The protocol version
changes only for incompatible wire breaks; additive features are negotiated
through capabilities.

## 2026-07-26

- Corrected the four fragmentation vectors so their reassembled payload is a
  valid JSON string, `"Hello World"`, instead of bytes that no negotiated
  encoding can decode.
- Regenerated `frame_fragment_first.bin`, `frame_fragment_last.bin`,
  `frame_fragment_correlated_first.bin`, and `frame_fragment_correlated_last.bin`
  with the new lengths and fragment data, and realigned every companion
  annotation.
- Added an explicit `context.encoding` field to every application-frame vector
  annotation so each vector is a complete decode oracle on its own.
- Stated in the status-code boundary that an application payload undecodable
  with the session's negotiated encoding after reassembly is
  `ERR_PROTOCOL_VIOLATION (403)`, resolving the latent conflict between the
  reassembly and malformed-payload conformance cases.

## 2026-07-23

- Defined the numbered Engine Conformance Suite as the shared acceptance
  criterion for the C++, Python, Rust, and TypeScript engine SDKs.
- Covered configuration, endpoint security and lifecycle, handshake rejection
  and negotiation, concurrent session isolation, frame safety, Control
  behaviour, correlation, events, and engine-side sends.
- Distinguished mandatory baseline cases from correlation-capability cases and
  identified the canonical vector consumed by every applicable test.

## 2026-07-22

- Defined the language-neutral Engine API contract for endpoint lifecycle,
  isolated sessions, engine-side handshake negotiation, security, callbacks,
  and correlated and uncorrelated sends.
- Declared process startup, shutdown decisions, restart policy, application
  semantics, and a `Runner` equivalent outside the Engine API contract.
- Corrected the project overview to distinguish the Go Client API from the four
  engine SDKs and to reflect the alpha version 1 platform-native protocol.
- Returned the unreleased specification to alpha status and protocol version 1.
- Replaced the cross-platform Unix socket requirement with Unix domain sockets
  on Linux/macOS and Named Pipes on Windows so every supported runtime can use
  its native local stream transport.
- Defined deterministic token-bearing endpoint addresses, stale endpoint
  detection, Unix permissions, and Windows pipe ACL requirements.
- Added isolated multi-connection sessions with engine-assigned session IDs and
  explicit reconnection state reset.
- Replaced the handshake reserved bytes with a negotiated 24-bit capability
  mask and assigned the correlation capability.
- Added request/response correlation, including deterministic prefix ordering
  when correlation and fragmentation are combined.
- Added payload-too-large and unsupported-encoding status codes with distinct
  boundaries from structural protocol violations.
- Separated protocol version, capability negotiation, and independent SDK
  library versions to prevent additive features from changing compatibility.
- Regenerated every handshake vector with protocol version 1 and replaced the
  reserved handshake and ACK annotations with capability masks.
- Added positive and rejection vectors for capability intersection, encoding
  negotiation, sessions, correlation, and combined correlation fragmentation.
- Realigned oversized-frame and Control error vectors with
  `ERR_PAYLOAD_TOO_LARGE (413)` and documented every binary field in its JSON
  companion.
