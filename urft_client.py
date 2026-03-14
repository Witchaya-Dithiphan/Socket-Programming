import sys
import socket
import struct
import os
import time

# Header format: [Type(1 byte)] [SeqNum(4 bytes)] [PayloadLen(2 bytes)]
HEADER_FORMAT = '!BIH'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
PAYLOAD_SIZE = 1393
PACKET_SIZE = HEADER_SIZE + PAYLOAD_SIZE

# Packet Types
TYPE_SYN = 0
TYPE_SYN_ACK = 1
TYPE_DATA = 2
TYPE_ACK = 3
TYPE_FIN = 4
TYPE_FIN_ACK = 5

WINDOW_SIZE = 128
RTO = 0.32

def start_client(file_path, server_ip, server_port):
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' not found.")
        sys.exit(1)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.01) # Small timeout to enable fast loop
    server_addr = (server_ip, server_port)

    # 1. Handshake
    filename = os.path.basename(file_path).encode('utf-8')
    syn_pkt = struct.pack(HEADER_FORMAT, TYPE_SYN, 0, len(filename)) + filename
    
    handshake_done = False
    syn_sent_time = 0
    print(f"Connecting to server {server_ip}:{server_port}...")
    while not handshake_done:
        curr_time = time.time()
        if curr_time - syn_sent_time > RTO:
            sock.sendto(syn_pkt, server_addr)
            syn_sent_time = curr_time
        
        try:
            data, addr = sock.recvfrom(2048)
            if addr != server_addr or len(data) < HEADER_SIZE:
                continue
            pkt_type, _, _ = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
            if pkt_type == TYPE_SYN_ACK:
                handshake_done = True
                print("Handshake complete.")
        except socket.timeout:
            pass
        except KeyboardInterrupt:
            print("\nSetup cancelled by user.")
            sock.close()
            sys.exit(1)

    # 2. Prepare chunks
    chunks = []
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(PAYLOAD_SIZE)
            if not chunk:
                break
            chunks.append(chunk)
            
    total_chunks = len(chunks)
    print(f"File grouped into {total_chunks} chunks.")

    # 3. Transfer (Selective Repeat)
    base = 0
    next_seq = 0
    sent_times = {}
    acked = set()

    start_time = time.time()
    last_print_base = -1
    
    while base < total_chunks:
        # Transmit new packets in the window
        while next_seq < base + WINDOW_SIZE and next_seq < total_chunks:
            if next_seq not in sent_times:
                payload = chunks[next_seq]
                pkt = struct.pack(HEADER_FORMAT, TYPE_DATA, next_seq, len(payload)) + payload
                sock.sendto(pkt, server_addr)
                sent_times[next_seq] = time.time()
            next_seq += 1
            
        # Receive ACKs
        try:
            data, addr = sock.recvfrom(2048)
            if addr == server_addr and len(data) >= HEADER_SIZE:
                pkt_type, seq_num, _ = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
                if pkt_type == TYPE_ACK:
                    acked.add(seq_num)
                    # Slide window
                    while base in acked:
                        base += 1
        except socket.timeout:
            pass
            
        # Handle retransmissions for packets in the window
        curr_time = time.time()
        for seq in range(base, next_seq):
            if seq not in acked:
                if curr_time - sent_times[seq] > RTO:
                    payload = chunks[seq]
                    pkt = struct.pack(HEADER_FORMAT, TYPE_DATA, seq, len(payload)) + payload
                    sock.sendto(pkt, server_addr)
                    sent_times[seq] = curr_time
                    
        # Print progress
        if total_chunks > 0 and base != last_print_base and base % max(1, total_chunks // 100) == 0:
            sys.stdout.write(f"\rProgress: {base}/{total_chunks} ({(base/total_chunks)*100:.2f}%)")
            sys.stdout.flush()
            last_print_base = base

    sys.stdout.write(f"\rProgress: {total_chunks}/{total_chunks} (100.00%)\n")
    print(f"Data transferred in {time.time() - start_time:.2f} seconds.")

    # 4. Teardown
    fin_pkt = struct.pack(HEADER_FORMAT, TYPE_FIN, total_chunks, 0)
    teardown_done = False
    fin_sent_time = 0
    teardown_attempts = 0
    
    while not teardown_done and teardown_attempts < 10:
        curr_time = time.time()
        if curr_time - fin_sent_time > RTO:
            sock.sendto(fin_pkt, server_addr)
            fin_sent_time = curr_time
            teardown_attempts += 1
            
        try:
            data, addr = sock.recvfrom(2048)
            if addr == server_addr and len(data) >= HEADER_SIZE:
                pkt_type, _, _ = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
                if pkt_type == TYPE_FIN_ACK:
                    teardown_done = True
                    print("Teardown complete (FIN_ACK received).")
        except socket.timeout:
            pass
            
    sock.close()
    print("Client exiting gracefully.")

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python urft_client.py <file_path> <server_ip> <server_port>")
        sys.exit(1)
        
    file_path = sys.argv[1]
    server_ip = sys.argv[2]
    server_port = int(sys.argv[3])
    
    start_client(file_path, server_ip, server_port)