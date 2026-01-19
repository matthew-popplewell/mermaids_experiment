#!/bin/bash
# start_server.sh - Start INDI server for Star Adventurer GTi mount(s)
#
# Usage:
#   ./start_server.sh          # Auto-detect and start all connected mounts
#   ./start_server.sh 1        # Start with 1 mount instance
#   ./start_server.sh 4        # Start with 4 mount instances

set -e

NUM_MOUNTS=${1:-0}  # 0 = auto-detect

echo 'Cleaning up old processes...'
killall -9 indiserver 2>/dev/null || true
killall -9 indi_staradventurergti_telescope 2>/dev/null || true
sleep 1

# Auto-detect number of mounts if not specified
if [ "$NUM_MOUNTS" -eq 0 ]; then
    NUM_MOUNTS=$(ls /dev/ttyACM* 2>/dev/null | wc -l)
    if [ "$NUM_MOUNTS" -eq 0 ]; then
        echo "ERROR: No mounts detected (no /dev/ttyACM* devices)"
        echo "Check that mounts are powered on and connected via USB"
        exit 1
    fi
    echo "Auto-detected $NUM_MOUNTS mount(s)"
fi

echo "Starting INDI Server for $NUM_MOUNTS mount(s)..."

# Build the indiserver command with named driver instances
CMD="indiserver -v"
for i in $(seq 1 $NUM_MOUNTS); do
    CMD="$CMD indi_staradventurergti_telescope -n \"Mount $i\""
done

echo "Command: $CMD"
echo ""
echo "Mounts will appear as: Mount 1, Mount 2, etc."
echo "Use './multi_mount.py status' to check connections"
echo ""

# Run the server (this blocks)
eval $CMD
