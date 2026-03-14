#!/bin/bash

#ComNet - All Testcase Bash

# ======================================================================
# Automated UDP Reliable Transfer Tester (1-8 Test Cases)
# ======================================================================

usage() {
   echo "Usage: sudo ./test_case.sh <test_case_number_1_to_8>"
   echo "Example: sudo ./test_case.sh"
   exit 1
}

if [ -z "$1" ]; then
   usage
fi

TEST_CASE=$1
FILE_SIZE_MB=1
RTT=10
C2S_LOSS=0
C2S_DUP=0
C2S_REORDER=0
S2C_LOSS=0
S2C_DUP=0
TIMEOUT_SEC=30
POINTS=3

if [ "$TEST_CASE" -eq 1 ]; then
   echo ">> Running Test Case 1: 1 MiB, RTT 10ms, No Loss"
elif [ "$TEST_CASE" -eq 2 ]; then
   echo ">> Running Test Case 2: 1 MiB, RTT 10ms, C2S Dup 2%"
   C2S_DUP=2
elif [ "$TEST_CASE" -eq 3 ]; then
   echo ">> Running Test Case 3: 1 MiB, RTT 10ms, C2S Loss 2%"
   C2S_LOSS=2
elif [ "$TEST_CASE" -eq 4 ]; then
   echo ">> Running Test Case 4: 1 MiB, RTT 10ms, S2C Dup 5%"
   S2C_DUP=5
elif [ "$TEST_CASE" -eq 5 ]; then
   echo ">> Running Test Case 5: 1 MiB, RTT 10ms, S2C Loss 5%"
   S2C_LOSS=5
   POINTS=2
elif [ "$TEST_CASE" -eq 6 ]; then
   echo ">> Running Test Case 6: 1 MiB, RTT 250ms, No Loss"
   RTT=250
   TIMEOUT_SEC=60
   POINTS=2
elif [ "$TEST_CASE" -eq 7 ]; then
   echo ">> Running Test Case 7: 1 MiB, RTT 250ms, C2S Reorder 2%"
   RTT=250
   C2S_REORDER=2
   TIMEOUT_SEC=90
   POINTS=2
elif [ "$TEST_CASE" -eq 8 ]; then
   echo ">> Running Test Case 8: 5 MiB, RTT 100ms, C2S Loss 5%, S2C Loss 2%"
   FILE_SIZE_MB=5
   RTT=100
   C2S_LOSS=5
   S2C_LOSS=2
   POINTS=2
else
   echo "Invalid Test Case Number. Choose between 1 and 8."
   exit 1
fi

DELAY_MS=$((RTT / 2))

# Cleanup any previous runs
sudo ip -all netns delete 2>/dev/null
sudo tc qdisc del dev lo root 2>/dev/null
rm -rf test_space
mkdir -p test_space/server test_space/client
cp urft_server.py test_space/server/
cp urft_client.py test_space/client/

echo "[1/4] Setting up Network Namespaces..."
sudo ip netns add server_ns
sudo ip netns add client_ns
sudo ip netns add router_ns

sudo ip link add s_veth0 type veth peer name r_veth1
sudo ip link add c_veth0 type veth peer name r_veth2
sudo ip link set s_veth0 netns server_ns
sudo ip link set r_veth1 netns router_ns
sudo ip link set c_veth0 netns client_ns
sudo ip link set r_veth2 netns router_ns

sudo ip netns exec server_ns ip addr add 192.168.1.2/24 dev s_veth0
sudo ip netns exec server_ns ip link set s_veth0 up
sudo ip netns exec server_ns ip link set lo up
sudo ip netns exec server_ns ip route add default via 192.168.1.1 

sudo ip netns exec client_ns ip addr add 192.168.2.3/24 dev c_veth0
sudo ip netns exec client_ns ip link set c_veth0 up
sudo ip netns exec client_ns ip link set lo up
sudo ip netns exec client_ns ip route add default via 192.168.2.1 

sudo ip netns exec router_ns ip addr add 192.168.1.1/24 dev r_veth1
sudo ip netns exec router_ns ip link set r_veth1 up
sudo ip netns exec router_ns ip addr add 192.168.2.1/24 dev r_veth2
sudo ip netns exec router_ns ip link set r_veth2 up
sudo ip netns exec router_ns sysctl -w net.ipv4.ip_forward=1 > /dev/null

echo "[2/4] Applying Traffic Control (tc netem) Rules..."
C2S_TC="delay ${DELAY_MS}ms"
if [ "$C2S_LOSS" -gt 0 ]; then C2S_TC="$C2S_TC loss $C2S_LOSS%"; fi
if [ "$C2S_DUP" -gt 0 ]; then C2S_TC="$C2S_TC duplicate $C2S_DUP%"; fi
if [ "$C2S_REORDER" -gt 0 ]; then C2S_TC="$C2S_TC reorder $C2S_REORDER%"; fi
sudo ip netns exec router_ns tc qdisc add dev r_veth1 root netem $C2S_TC

S2C_TC="delay ${DELAY_MS}ms"
if [ "$S2C_LOSS" -gt 0 ]; then S2C_TC="$S2C_TC loss $S2C_LOSS%"; fi
if [ "$S2C_DUP" -gt 0 ]; then S2C_TC="$S2C_TC duplicate $S2C_DUP%"; fi
sudo ip netns exec router_ns tc qdisc add dev r_veth2 root netem $S2C_TC


echo "[3/4] Generating $FILE_SIZE_MB MiB Test File..."
cd test_space/client
head -c $((FILE_SIZE_MB * 1048576)) </dev/urandom > v_test.bin
ORIGINAL_MD5=$(md5sum v_test.bin | awk '{print $1}')

cd ../server
echo "[4/4] Starting Transfer (Timeout limit: $TIMEOUT_SEC seconds)"
sudo ip netns exec server_ns python3 urft_server.py 192.168.1.2 8888 &
SERVER_PID=$!
sleep 1 

cd ../client
# Start client with timeout limitation
sudo timeout $TIMEOUT_SEC ip netns exec client_ns python3 urft_client.py v_test.bin 192.168.1.2 8888
CLIENT_EXIT_CODE=$?

cd ../server
if [ $CLIENT_EXIT_CODE -eq 124 ]; then
   echo -e "\nFAILED: Timeout! File transfer took longer than $TIMEOUT_SEC seconds."
elif [ -f "v_test.bin" ]; then
   RECV_MD5=$(md5sum v_test.bin | awk '{print $1}')
   if [ "$ORIGINAL_MD5" = "$RECV_MD5" ]; then
      echo -e "\n 🎉✅ SUCCESS! MD5 matched exactly."
      echo "Score: $POINTS Points"
   else
      echo -e "\n ❌❌ FAILED: MD5 Mismatch."
   fi
else
   echo -e "\n ❌❌ FAILED: Output file was not created on the server."
fi

sudo kill $SERVER_PID 2>/dev/null || true
cd ../../
sudo ip -all netns delete
rm -rf test_space