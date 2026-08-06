# Changelog

Protocol revisions are recorded as dated change entries. The protocol version
changes only for incompatible wire breaks; additive features are negotiated
through capabilities.

## 2026-08-05

- Added the single-SDK conformance and interoperability harness with a
  versioned machine-readable report, strict exit codes, owned-process cleanup,
  and mandatory completeness validation.
- Added autonomous spec validation on the three supported operating systems,
  immutable revision reporting, and negative gate proofs while leaving every
  SDK matrix in its owning repository.

## 2026-08-03

- Clarified that an engine responder always writes the correlated application
  response on `Data` while repeating the request correlation ID, matching the
  frozen Command-to-Data response vector and engine output-channel rules.

## 2026-07-30

- Replaced the old topology suite with distinct executable Client-listener and
  common Engine-dialer conformance contracts.
- Added a machine-readable case manifest with stable IDs, deterministic case
  structure, exact normative traceability, platform requirements, and a record
  of removed listener-engine cases.
- Added validation for duplicate or uncovered requirements, missing vectors,
  role drift, application-shaped payloads, permanent platform skips, and
  skipped mandatory results.
- Added Windows, Linux, and macOS CI validation for vectors and conformance
  contracts while reserving SDK harness implementation for Task 15.
- Confirmed all 25 canonical wire binaries and their SHA-256 values unchanged
  after listener ownership inversion.
- Added deterministic machine-readable vectors for Windows and Unix address
  derivation, macOS pathname boundaries, and invalid configuration inputs.
- Added a generated fixture manifest that classifies every wire vector and pins
  exact binary and annotation hashes.
- Replaced semantic-only CI checks with exact byte, address, manifest, and
  protocol version 1 validation through `tools/vector_tool.py`.

## 2026-07-29

- Moved listener ownership to the Go client and defined every engine as a
  transport dialer while preserving the Go-to-engine handshake direction.
- Made the one-to-one topology mandatory and required Go to continue accepting
  after rejecting an invalid engine candidate.
- Moved endpoint creation, stale-endpoint cleanup, Unix permissions, and
  Windows Named Pipe access control to Go.
- Defined the macOS Unix socket pathname limit as 103 encoded bytes plus the
  terminating NUL and replaced the clear Unix stem with the canonical compact
  SHA-256-derived filename.
- Required each endpoint to replace its opaque local generation for every
  established session so stale operations cannot act on a later connection.
- Added reproducible minimum-name, maximum-name, and macOS 103/104-byte address
  examples shared by all five SDKs.
- Realigned the Go Client API and both conformance suites around Go admission
  and engine dialling without adding process lifecycle policy.
- Kept protocol version `1` and every existing handshake, ACK, Control, and
  frame vector byte unchanged; Task 02 only confirms them and adds address
  derivation fixtures.

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
  explicit reconnection state reset; listener inversion superseded the
  multi-connection topology with mandatory 1:1 operation on 2026-07-29.
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
