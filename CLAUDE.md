# CLAUDE.md

Guidance for Claude Code (and other AI assistants) when working in this repository.

## Project overview

**URFT (UDP-based Reliable File Transfer)** is a KMITL Computer Networks assignment. It implements a reliable file-transfer protocol entirely in user space on top of UDP, in pure Python 3 with no third-party dependencies. The client sends a file to the server across a lossy/duplicating/re-ordering network; the server must reconstruct it byte-for-byte (verified by `md5sum`).

See `README.md` for the user-facing description and `assignment.txt` for the original specification.

## Components

- `urft_client.py` — sender. Handshake → Selective Repeat data transfer → teardown.
- `urft_server.py` — receiver. Single UDP socket, state machine `LISTEN → TRANSFER → TIME_WAIT`.
- `test_case.sh` — Linux network-namespace + `tc netem` harness for the 8 grading scenarios.

## Architecture notes

### Wire protocol
- Header: `struct` format `!BIH` = `[Type:1B][SeqNum:4B][PayloadLen:2B]`, then payload.
- 6 packet types: `SYN(0)`, `SYN_ACK(1)`, `DATA(2)`, `ACK(3)`, `FIN(4)`, `FIN_ACK(5)`.
- `PAYLOAD_SIZE = 1393` → 1400-byte packets, below typical MTU to avoid IP fragmentation.

### Client (`urft_client.py`)
- Non-blocking-ish loop: socket timeout 0.01 s.
- Handshake: resend `SYN` (with filename) every `RTO` until `SYN_ACK`.
- Data: Selective Repeat with `WINDOW_SIZE = 128`. Tracks `base`, `next_seq`, `sent_times`, `acked`. Retransmits any in-window unacked packet older than `RTO = 0.32 s`.
- Teardown: send `FIN` (seq = total chunk count), wait for `FIN_ACK`, up to 10 attempts.

### Server (`urft_server.py`)
- Single UDP socket, timeout 0.1 s.
- ACKs **every** received `DATA` packet (idempotent).
- In-order writes immediately; out-of-order chunks held in `buffer` dict and flushed when the gap closes; chunks below `expected_seq` are duplicates → re-ACK only.
- `TIME_WAIT` for `TIME_WAIT_DURATION = 2.0 s` to answer retransmitted `FIN`s, then exits.

## Hard constraints (do not violate)

These come from the assignment and must be preserved in any change:

- **Python 3.8+, standard library only** — no `pip install`, no external packages.
- **UDP only** — no TCP sockets anywhere.
- **Exactly one socket on the server side.**
- **≤ 5 source files**, **< 2000 total lines** across all source.
- Filenames `urft_server.py` and `urft_client.py` are fixed by the grader — do not rename.
- After launch, neither program may read further keyboard input.
- Both must exit cleanly (no traceback, return to shell) on success.
- Must run on Linux (grading environment).

## Running and testing

- Manual local run (works on any OS with Python):
  ```bash
  python urft_server.py 127.0.0.1 8888
  python urft_client.py ./test_file.bin 127.0.0.1 8888
  ```
- Full graded scenarios (Linux + root only):
  ```bash
  sudo ./test_case.sh <1-8>
  ```
  The harness builds client/router/server namespaces, applies `tc netem` impairments, runs the transfer under a timeout, and compares `md5sum`.

## Development notes

- This repo is developed on Windows but **graded on Linux** — keep code OS-portable and avoid Windows-only assumptions.
- Tuning `WINDOW_SIZE` and `RTO` is the main lever for passing the high-RTT / high-loss cases (6, 7, 8) within the time limit.
- The `*.bin` files are test artifacts, not source.
- When editing protocol logic, change client and server together — the header format and packet-type constants are duplicated in both files and must stay in sync.
