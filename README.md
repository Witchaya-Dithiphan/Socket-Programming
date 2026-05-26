# URFT — UDP-based Reliable File Transfer

A from-scratch implementation of a **reliable file-transfer protocol built on top of UDP**, written in pure Python 3 (standard library only). The project demonstrates how the reliability guarantees normally provided by TCP — ordered, complete, loss-free delivery — can be re-created at the application layer over an unreliable datagram transport.

This was developed as the Socket Programming assignment for **01076116 Computer Networks / 01076117 Computer Networks in Practice**, Computer Engineering, KMITL.

---

## What it does

A client reads a file from disk and transmits it to a server across a network that may **lose, duplicate, re-order, or delay** packets. Despite these conditions, the server reconstructs a byte-for-byte identical copy of the file (verified by `md5sum`).

The protocol is deliberately self-contained: no external libraries, no TCP, a single UDP socket per side.

---

## Highlights

- **Custom reliable protocol over UDP** — connection setup, reliable data transfer, and connection teardown, all hand-rolled.
- **Selective Repeat ARQ** with a sliding window (128 packets) for high throughput on high-latency links.
- **Per-packet ACKs, timeouts, and retransmission** to recover from packet loss.
- **Out-of-order buffering and duplicate detection** on the receiver so the output file is always assembled in the correct order with no duplicated bytes.
- **Binary-safe** — transfers any file type, not just text.
- **No third-party dependencies** — runs on a stock Python 3.8+ install.
- **Reproducible network-impairment test harness** using Linux network namespaces and `tc netem`.

---

## Repository layout

| File | Purpose |
|------|---------|
| `urft_client.py` | Client: reads the file, runs the handshake, sends data with a sliding window, performs teardown. |
| `urft_server.py` | Server: listens on a single UDP socket, reassembles the file, acknowledges packets, performs teardown. |
| `test_case.sh` | Automated test harness that builds an isolated 3-node network (client / router / server) and replays the 8 grading scenarios. |
| `assignment.txt` | Original assignment specification. |
| `Socket Programming Assignment.pdf` | Original assignment (PDF). |
| `*.bin` | Sample / generated test files. |

---

## Usage

Both programs take their parameters from the command line and require no further interactive input once started.

### Server

```bash
python urft_server.py <server_ip> <server_port>
```

The server binds to the given address, waits for a single client, writes the received bytes to a file named by the client, and exits cleanly after the transfer completes.

### Client

```bash
python urft_client.py <file_path> <server_ip> <server_port>
```

The client connects to the server, announces the filename, streams the file, prints progress, and exits cleanly once the server has acknowledged the teardown.

### Example

```bash
# Terminal 1
python urft_server.py 127.0.0.1 8888

# Terminal 2
python urft_client.py ./test_file.bin 127.0.0.1 8888
```

---

## How the protocol works

### Packet format

Every datagram begins with a fixed 7-byte header (`struct` format `!BIH`) followed by an optional payload:

```
+-----------+------------------+--------------------+------------------+
| Type      | Sequence Number  | Payload Length     | Payload          |
| (1 byte)  | (4 bytes)        | (2 bytes)          | (≤ 1393 bytes)   |
+-----------+------------------+--------------------+------------------+
```

The 1393-byte payload keeps the full packet at 1400 bytes, comfortably below a typical 1500-byte Ethernet MTU to avoid IP fragmentation.

**Packet types**

| Value | Type | Direction | Meaning |
|-------|------|-----------|---------|
| 0 | `SYN` | client → server | Open connection; payload carries the filename |
| 1 | `SYN_ACK` | server → client | Connection accepted |
| 2 | `DATA` | client → server | A file chunk identified by its sequence number |
| 3 | `ACK` | server → client | Acknowledges a specific data sequence number |
| 4 | `FIN` | client → server | All data sent; request teardown |
| 5 | `FIN_ACK` | server → client | Teardown acknowledged |

### 1. Connection setup (handshake)

The client repeatedly sends `SYN` (with the filename) until it receives a `SYN_ACK`, retransmitting every RTO (0.32 s) in case either packet is lost. The server, on `SYN`, opens the output file and replies with `SYN_ACK`. If the client's `SYN` arrives again later (because its `SYN_ACK` was lost), the server simply re-sends `SYN_ACK`.

### 2. Reliable data transfer (Selective Repeat)

- The file is split into fixed-size chunks, each tagged with a monotonically increasing sequence number.
- **Client** keeps a sliding window of up to `WINDOW_SIZE = 128` unacknowledged packets. It sends every packet in the window, records the time each was sent, and:
  - slides `base` forward as ACKs arrive,
  - retransmits any in-window packet whose ACK has not arrived within the RTO.
- **Server** ACKs *every* `DATA` packet it receives. It writes a chunk to disk immediately if it is the next expected sequence number; out-of-order chunks are held in a buffer and flushed in order once the gap is filled; chunks below the expected number are duplicates and are simply re-ACKed.

This combination tolerates loss (retransmission), duplication (idempotent writes + buffering), and re-ordering (the receiver buffer).

### 3. Connection teardown

After the last ACK, the client sends `FIN` (carrying the total chunk count) and waits for `FIN_ACK`, retrying up to 10 times. The server replies with `FIN_ACK`, closes the file, and enters a `TIME_WAIT` state for 2 seconds so it can answer any retransmitted `FIN` before exiting gracefully.

### Reliability mechanism summary

| Network problem | How it is handled |
|-----------------|-------------------|
| Packet loss | Timeout + retransmission of unacknowledged packets |
| Packet duplication | Receiver ignores already-written sequence numbers; ACKs are idempotent |
| Packet re-ordering | Receiver buffers out-of-order chunks and writes them in sequence order |
| High latency (RTT) | Large sliding window keeps many packets in flight |
| Lost control packets | SYN/FIN are retransmitted; SYN_ACK/FIN_ACK are re-sent on duplicate requests |

---

## Testing

`test_case.sh` reproduces the eight grading scenarios on a single Linux host. It builds three network namespaces — client, router, and server, on separate subnets — and uses `tc netem` on the router to inject latency, loss, duplication, and re-ordering. After each transfer it compares the `md5sum` of the received file against the original.

```bash
sudo ./test_case.sh <test_case_number_1_to_8>
```

| # | File | RTT | Impairment |
|---|------|-----|------------|
| 1 | 1 MiB | 10 ms | none |
| 2 | 1 MiB | 10 ms | client→server duplication 2% |
| 3 | 1 MiB | 10 ms | client→server loss 2% |
| 4 | 1 MiB | 10 ms | server→client duplication 5% |
| 5 | 1 MiB | 10 ms | server→client loss 5% |
| 6 | 1 MiB | 250 ms | none |
| 7 | 1 MiB | 250 ms | client→server re-ordering 2% |
| 8 | 5 MiB | 100 ms | client→server loss 5%, server→client loss 2% |

> The harness requires root (for namespaces and `tc`) and runs on Linux.

---

## Design constraints

The implementation respects the assignment's limits:

- Python 3.8+, standard library only.
- UDP as the only transport protocol.
- A single UDP socket on the server side.
- At most 5 source files and under 2000 total lines of code.
- Runs on Linux with no installation step.

---

## Key configuration

| Constant | Value | Where | Meaning |
|----------|-------|-------|---------|
| `PAYLOAD_SIZE` | 1393 bytes | both | Bytes of file data per packet |
| `WINDOW_SIZE` | 128 | client | Max in-flight unacknowledged packets |
| `RTO` | 0.32 s | client | Retransmission timeout |
| `TIME_WAIT_DURATION` | 2.0 s | server | Grace period to answer retransmitted FINs |
