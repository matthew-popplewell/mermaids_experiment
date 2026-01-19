#!/bin/bash
# install_dependencies.sh

set -e

if [ "$EUID" -eq 0 ]; then
  echo 'Error: Please do not run this script with sudo. It will ask for password when needed.'
  exit 1
fi

echo '--- [1/3] Installing System INDI Components ---'
sudo apt-add-repository ppa:mutlaqja/ppa -y
sudo apt-get update
sudo apt-get install -y indi-bin indi-eqmod python3-indi-client libindi-dev python3.10 python3.10-venv

echo '--- [2/3] Adding user to dialout group (for serial port access) ---'
sudo usermod -a -G dialout "$USER"

echo '--- [3/3] Installing Python Libraries for Python 3.10 ---'
python3.10 -m pip install --user plotly

echo ''
echo '=== Setup Complete ==='
echo 'NOTE: Log out and back in for dialout group permissions to take effect.'
echo ''
echo 'To run the mount control:'
echo '  Terminal 1: ./start_server.sh'
echo '  Terminal 2: ./point_mount.py'
