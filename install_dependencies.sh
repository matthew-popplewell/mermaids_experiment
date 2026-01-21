#!/bin/bash
# install_dependencies.sh
#
# Unified installation script with online/offline mode support.
#
# Usage:
#   ./install_dependencies.sh           # Auto-detect mode
#   ./install_dependencies.sh --offline # Force offline mode
#   ./install_dependencies.sh --online  # Force online mode

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OFFLINE_DIR="$SCRIPT_DIR/offline_packages"

# --- Parse arguments ---
MODE=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --offline)
            MODE="offline"
            shift
            ;;
        --online)
            MODE="online"
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--offline|--online]"
            echo ""
            echo "Options:"
            echo "  --offline  Force offline installation from pre-downloaded packages"
            echo "  --online   Force online installation (download from internet)"
            echo "  (none)     Auto-detect based on internet connectivity and package availability"
            echo ""
            echo "For offline installation, first run prepare_offline_packages.sh on an"
            echo "internet-connected machine, then copy the project to your target machine."
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information."
            exit 1
            ;;
    esac
done

# --- Check if running as root ---
if [ "$EUID" -eq 0 ]; then
    echo 'Error: Please do not run this script with sudo. It will ask for password when needed.'
    exit 1
fi

# --- Auto-detect mode if not specified ---
check_internet() {
    # Try to reach a reliable server
    if curl -s --connect-timeout 3 https://pypi.org > /dev/null 2>&1; then
        return 0
    elif ping -c 1 -W 3 8.8.8.8 > /dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

has_offline_packages() {
    [ -d "$OFFLINE_DIR" ] && \
    [ -f "$OFFLINE_DIR/manifest.json" ] && \
    [ -f "$OFFLINE_DIR/uv/uv" ]
}

if [ -z "$MODE" ]; then
    echo "Auto-detecting installation mode..."

    if has_offline_packages; then
        if check_internet; then
            echo "Offline packages found and internet available."
            echo "Using online mode (for latest packages). Use --offline to force offline."
            MODE="online"
        else
            echo "Offline packages found and no internet detected."
            echo "Using offline mode."
            MODE="offline"
        fi
    else
        if check_internet; then
            echo "No offline packages found, internet available."
            echo "Using online mode."
            MODE="online"
        else
            echo "Error: No offline packages and no internet connection."
            echo "Either:"
            echo "  1. Connect to the internet and run this script again, or"
            echo "  2. Run prepare_offline_packages.sh on another machine and copy the project here"
            exit 1
        fi
    fi
    echo ""
fi

# --- Execute appropriate installation ---
if [ "$MODE" = "offline" ]; then
    echo "=== Running Offline Installation ==="
    echo ""

    if ! has_offline_packages; then
        echo "Error: Offline packages not found at $OFFLINE_DIR"
        echo "Run prepare_offline_packages.sh on an internet-connected machine first."
        exit 1
    fi

    # Delegate to install_offline.sh
    exec "$SCRIPT_DIR/install_offline.sh"
fi

# --- Online Installation ---
echo "=== Running Online Installation ==="
echo ""

echo '--- [1/6] Installing System Dependencies ---'
sudo apt-add-repository ppa:mutlaqja/ppa -y
sudo apt-get update
sudo apt-get install -y \
    indi-bin indi-eqmod python3-indi-client libindi-dev \
    libusb-1.0-0-dev \
    libcfitsio-dev

echo '--- [2/6] Adding user to dialout group (for serial port access) ---'
sudo usermod -a -G dialout "$USER"

echo '--- [3/6] Initializing git submodules ---'
git submodule update --init --recursive
cd asi_driver && git checkout dev && cd ..

echo '--- [4/6] Installing ASI Camera udev rules ---'
sudo install -m 644 asi_driver/ASI_linux_mac_SDK_V1.41/lib/asi.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger

echo '--- [5/6] Installing uv (Python package manager) ---'
if ! command -v uv &> /dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
else
    echo "uv already installed"
fi

echo '--- [6/6] Installing Python dependencies with uv ---'
uv sync

echo ''
echo '=== Setup Complete ==='
echo ''
echo 'NOTE: Log out and back in for dialout group permissions to take effect.'
echo ''
echo 'To activate the Python environment:'
echo '  source .venv/bin/activate'
echo ''
echo 'To run the mount control:'
echo '  Terminal 1: ./start_server.sh'
echo '  Terminal 2: python mount_driver/point_mount.py'
echo ''
echo 'To run ASI camera commands:'
echo '  asi-focus, asi-burst, asi-gps-test, asi-cam-setup'
echo ''
