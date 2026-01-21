#!/bin/bash
# start_server.sh - Start INDI server for Star Adventurer GTi mount(s)
#
# Usage:
#   ./start_server.sh          # Auto-detect and start all connected mounts
#   ./start_server.sh 1        # Start with 1 mount instance
#   ./start_server.sh 4        # Start with 4 mount instances
#
# The server starts, then automatically connects all mounts.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
if [ "$NUM_MOUNTS" -eq 1 ]; then
    # Single mount mode - use default device name
    CMD="indiserver -v indi_staradventurergti_telescope"
    DEVICE_NAME="Star Adventurer GTi"
else
    # Multi-mount mode - create wrapper scripts with INDIDEV set for each mount
    CMD="indiserver -v"
    for i in $(seq 1 $NUM_MOUNTS); do
        WRAPPER="$SCRIPT_DIR/.mount${i}_driver.sh"
        cat > "$WRAPPER" << WRAPPER_EOF
#!/bin/bash
export INDIDEV="Mount $i"
exec indi_staradventurergti_telescope "\$@"
WRAPPER_EOF
        chmod +x "$WRAPPER"
        CMD="$CMD $WRAPPER"
    done
    DEVICE_NAME="Mount"
fi

echo "Command: $CMD"
echo ""

# Start server in background
eval $CMD &
SERVER_PID=$!

# Wait for server to be ready
echo "Waiting for INDI server to initialize..."
sleep 3

# Auto-connect all mounts
echo "Connecting mounts..."
if [ "$NUM_MOUNTS" -eq 1 ]; then
    indi_setprop "Star Adventurer GTi.CONNECTION.CONNECT=On" 2>/dev/null && echo "  Connected: Star Adventurer GTi" || echo "  Warning: Could not connect mount"
else
    # Use multi_mount.py to auto-assign ports and connect
    "$SCRIPT_DIR/multi_mount.py" connect
fi

echo ""
echo "Server running (PID: $SERVER_PID)"
if [ "$NUM_MOUNTS" -eq 1 ]; then
    echo "Use './point_mount.py' for single mount control"
else
    echo "Mounts appear as: Mount 1, Mount 2, etc."
    echo "Use './multi_mount.py status' to check connections"
fi
echo "Press Ctrl+C to stop"
echo ""

# Wait for server (brings it to foreground for Ctrl+C)
wait $SERVER_PID
