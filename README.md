# yuumi-spec

> Canonical protocol repository for the Yuumi ecosystem.

This repository is the source of truth for the wire protocol used by all Yuumi SDKs.
It intentionally contains protocol documentation and conformance vectors only.

## Specification

- Protocol document: [`PROTOCOL.md`](./PROTOCOL.md)
- Canonical binary vectors: [`test-vectors/`](./test-vectors/)

Any implementation in any language must conform to these artifacts.

## SDK repositories

| Language | Repository | Install |
|---|---|---|
| Go (client / TUI side) | [yuumi](https://github.com/YuumiConnectionLibrary/yuumi) | `go get github.com/YuumiConnectionLibrary/yuumi` |
| C++ (server side) | [yuumi-cpp](https://github.com/YuumiConnectionLibrary/yuumi-cpp) | CMake + vcpkg |
| Python (planned) | `yuumi-py` | `pip install yuumi` |
| Rust (planned) | `yuumi-rs` | `cargo add yuumi` |

## Ecosystem direction

Yuumi is designed so that:

- Go is the UI/client layer (for example Charm-based TUI apps).
- Server business logic can run in the user's language of choice.
- All pairings converge on the same transport semantics through one protocol.
- Yuumi and Zeri are separate projects with no compatibility guarantees.

## Versioning

Protocol version is encoded in the handshake as `uint32`.
Current protocol version: **2**.
Breaking wire changes must increment the version and refresh test vectors.
