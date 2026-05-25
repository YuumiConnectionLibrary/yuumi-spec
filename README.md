# yuumi-spec

> Authoritative wire protocol specification for Yuumi IPC.

## What this repo is

This repository defines **the protocol** — not any implementation.
Every language SDK must conform to [`PROTOCOL.md`](./PROTOCOL.md).

## Implementations

| Language | Repo | Status |
|---|---|---|
| Go | [yuumi-go](https://github.com/ilmartotch/yuumi-go) | ✅ stable |
| C++ | [yuumi-cpp](https://github.com/ilmartotch/yuumi-cpp) | ✅ stable |
| Rust | yuumi-rs | 🔜 planned |

## Test vectors

[`test-vectors/`](./test-vectors/) contains canonical binary blobs with `.json` annotations
for field-by-field validation. Use them to verify any new implementation.

## Versioning

Protocol version is a `uint32` embedded in the handshake.
Current: **v2**. Changes that break wire compatibility increment this number.
