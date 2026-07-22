# Changelog

Protocol revisions are recorded as dated change entries. The protocol version
changes only for incompatible wire breaks; additive features are negotiated
through capabilities.

## 2026-07-22

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
