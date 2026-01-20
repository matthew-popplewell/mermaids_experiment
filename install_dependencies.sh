#!/bin/bash
# install_dependencies.sh

set -e

if [ "$EUID" -eq 0 ]; then
  echo 'Error: Please do not run this script with sudo. It will ask for password when needed.'
  exit 1
fi

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
