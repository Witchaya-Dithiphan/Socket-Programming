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

def start_server(ip, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((ip, port))
    sock.settimeout(0.1) # for select/timeout

    print(f"Server listening on {ip}:{port}")

    expected_seq = 0
    buffer = {} # For out-of-order packets
    file_ptr = None
    client_addr = None
    state = 'LISTEN'
    
    fin_time = None
    TIME_WAIT_DURATION = 2.0

    while True:
        try:
            data, addr = sock.recvfrom(2048)
            if len(data) < HEADER_SIZE:
                continue

            header = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
            pkt_type, seq_num, payload_len = header
            payload = data[HEADER_SIZE:HEADER_SIZE+payload_len]

            if state == 'LISTEN':
                if pkt_type == TYPE_SYN:
                    client_addr = addr
                    filename = payload.decode('utf-8')
                    filename = os.path.basename(filename)
                    file_ptr = open(filename, 'wb')
                    state = 'TRANSFER'
                    expected_seq = 0
                    buffer = {}
                    
                    # Send SYN_ACK
                    ack_pkt = struct.pack(HEADER_FORMAT, TYPE_SYN_ACK, 0, 0)
                    sock.sendto(ack_pkt, client_addr)
                    print(f"Handshake complete. Receiving file: {filename}")
            
            elif state == 'TRANSFER':
                if addr != client_addr:
                    continue # Ignore other clients
                
                if pkt_type == TYPE_SYN:
                    # Client might have lost SYN_ACK, resend
                    ack_pkt = struct.pack(HEADER_FORMAT, TYPE_SYN_ACK, 0, 0)
                    sock.sendto(ack_pkt, client_addr)
                
                elif pkt_type == TYPE_DATA:
                    ack_pkt = struct.pack(HEADER_FORMAT, TYPE_ACK, seq_num, 0)
                    sock.sendto(ack_pkt, client_addr) # Always ACK what we get

                    if seq_num == expected_seq:
                        file_ptr.write(payload)
                        expected_seq += 1
                        
                        # Check buffer for consecutive packets
                        while expected_seq in buffer:
                            file_ptr.write(buffer.pop(expected_seq))
                            expected_seq += 1
                    elif seq_num > expected_seq:
                        # Out of order
                        if seq_num not in buffer:
                            buffer[seq_num] = payload
                    # If seq_num < expected_seq, it's a duplicate, we already sent ACK.

                elif pkt_type == TYPE_FIN:
                    # Teardown
                    ack_pkt = struct.pack(HEADER_FORMAT, TYPE_FIN_ACK, seq_num, 0)
                    sock.sendto(ack_pkt, client_addr)
                    
                    if file_ptr:
                        file_ptr.close()
                        file_ptr = None
                    
                    state = 'TIME_WAIT'
                    fin_time = time.time()
                    print("FIN received. Entering TIME_WAIT.")
            
            elif state == 'TIME_WAIT':
                if addr != client_addr:
                    continue
                if pkt_type == TYPE_FIN:
                    # Resend FIN_ACK
                    ack_pkt = struct.pack(HEADER_FORMAT, TYPE_FIN_ACK, seq_num, 0)
                    sock.sendto(ack_pkt, client_addr)
        
        except socket.timeout:
            pass # Timeout is just for checking TIME_WAIT
        except KeyboardInterrupt:
            print("\nServer shutting down by user.")
            break
            
        if state == 'TIME_WAIT' and time.time() - fin_time > TIME_WAIT_DURATION:
            print("TIME_WAIT completed. Server exiting gracefully.")
            break

    if file_ptr:
        file_ptr.close()
    sock.close()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python urft_server.py <server_ip> <server_port>")
        sys.exit(1)
    
    server_ip = sys.argv[1]
    server_port = int(sys.argv[2])
    start_server(server_ip, server_port)
