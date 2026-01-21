#!/bin/bash
# install_offline.sh
# Installs all dependencies from pre-downloaded offline packages.
# Run prepare_offline_packages.sh on an internet-connected machine first.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OFFLINE_DIR="$SCRIPT_DIR/offline_packages"

# Detect system info
UBUNTU_CODENAME=$(lsb_release -cs 2>/dev/null || echo "unknown")
ARCH=$(uname -m)

echo "=== Offline Installation ==="
echo "Ubuntu codename: $UBUNTU_CODENAME"
echo "Architecture: $ARCH"
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo 'Error: Please do not run this script with sudo. It will ask for password when needed.'
    exit 1
fi

# Verify offline packages exist
if [ ! -d "$OFFLINE_DIR" ]; then
    echo "Error: Offline packages directory not found: $OFFLINE_DIR"
    echo "Run prepare_offline_packages.sh on an internet-connected machine first."
    exit 1
fi

# Check manifest
if [ -f "$OFFLINE_DIR/manifest.json" ]; then
    MANIFEST_CODENAME=$(grep -o '"ubuntu_codename": "[^"]*"' "$OFFLINE_DIR/manifest.json" | cut -d'"' -f4)
    MANIFEST_ARCH=$(grep -o '"architecture": "[^"]*"' "$OFFLINE_DIR/manifest.json" | cut -d'"' -f4)

    if [ "$MANIFEST_CODENAME" != "$UBUNTU_CODENAME" ]; then
        echo "Warning: Packages prepared for Ubuntu $MANIFEST_CODENAME, but running on $UBUNTU_CODENAME"
        echo "APT packages may not be compatible."
        read -p "Continue anyway? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi

    if [ "$MANIFEST_ARCH" != "$ARCH" ]; then
        echo "Error: Packages prepared for $MANIFEST_ARCH, but running on $ARCH"
        echo "Cannot continue - architecture mismatch."
        exit 1
    fi
fi

APT_DIR="$OFFLINE_DIR/apt/$UBUNTU_CODENAME"
WHEELS_DIR="$OFFLINE_DIR/python/wheels"
UV_BINARY="$OFFLINE_DIR/uv/uv"

# --- APT Packages ---
echo "--- [1/6] Installing APT packages ---"

if [ -d "$APT_DIR" ] && [ "$(ls -A "$APT_DIR"/*.deb 2>/dev/null)" ]; then
    DEB_COUNT=$(ls -1 "$APT_DIR"/*.deb 2>/dev/null | wc -l)
    echo "Installing $DEB_COUNT .deb packages from $APT_DIR..."

    # Install all .deb files
    # Use dpkg with --force-depends to handle missing dependencies from the bundle
    # Then run apt-get -f install to resolve any issues
    sudo dpkg -i "$APT_DIR"/*.deb 2>/dev/null || true

    # Try to fix any dependency issues with local packages only
    sudo apt-get install -f -y --no-download 2>/dev/null || {
        echo "Warning: Some dependencies could not be resolved offline."
        echo "The system may have existing packages that satisfy them."
    }

    echo "APT packages installed."
else
    echo "Warning: No .deb packages found in $APT_DIR"
    echo "Checking if packages are already installed..."

    # Check if required packages are already installed
    REQUIRED_PKGS="indi-bin libusb-1.0-0-dev libcfitsio-dev"
    MISSING=""
    for pkg in $REQUIRED_PKGS; do
        if ! dpkg -l "$pkg" 2>/dev/null | grep -q "^ii"; then
            MISSING="$MISSING $pkg"
        fi
    done

    if [ -n "$MISSING" ]; then
        echo "Error: Required packages not found and no offline packages available:$MISSING"
        exit 1
    fi
    echo "Required packages already installed."
fi

# --- User Groups ---
echo ""
echo "--- [2/6] Adding user to dialout group (for serial port access) ---"
sudo usermod -a -G dialout "$USER"

# --- Git Submodules ---
echo ""
echo "--- [3/6] Checking git submodules ---"
# Submodules should already be initialized if the project was copied correctly
if [ ! -d "$SCRIPT_DIR/asi_driver/tetra3/tetra3" ]; then
    echo "Warning: tetra3 submodule not fully initialized."
    echo "Attempting local initialization..."
    cd "$SCRIPT_DIR"
    git submodule update --init --recursive 2>/dev/null || {
        echo "Error: Could not initialize submodules offline."
        echo "Ensure submodules were included when copying the project."
        exit 1
    }
fi
cd "$SCRIPT_DIR/asi_driver" && git checkout dev 2>/dev/null || true
cd "$SCRIPT_DIR"
echo "Submodules OK."

# --- Udev Rules ---
echo ""
echo "--- [4/6] Installing ASI Camera udev rules ---"
if [ -f "$SCRIPT_DIR/asi_driver/ASI_linux_mac_SDK_V1.41/lib/asi.rules" ]; then
    sudo install -m 644 "$SCRIPT_DIR/asi_driver/ASI_linux_mac_SDK_V1.41/lib/asi.rules" /etc/udev/rules.d/
    sudo udevadm control --reload-rules
    sudo udevadm trigger
    echo "Udev rules installed."
else
    echo "Warning: ASI udev rules not found. Camera may not work without rules."
fi

# --- uv Package Manager ---
echo ""
echo "--- [5/6] Installing uv (Python package manager) ---"

UV_INSTALL_DIR="$HOME/.local/bin"
mkdir -p "$UV_INSTALL_DIR"

if [ -f "$UV_BINARY" ]; then
    cp "$UV_BINARY" "$UV_INSTALL_DIR/uv"
    chmod +x "$UV_INSTALL_DIR/uv"

    # Also copy uvx if present
    if [ -f "$OFFLINE_DIR/uv/uvx" ]; then
        cp "$OFFLINE_DIR/uv/uvx" "$UV_INSTALL_DIR/uvx"
        chmod +x "$UV_INSTALL_DIR/uvx"
    fi

    echo "uv installed to $UV_INSTALL_DIR/uv"
else
    echo "Warning: uv binary not found in offline packages."
    if command -v uv &> /dev/null; then
        echo "Using existing uv installation."
    else
        echo "Error: uv is required but not available."
        exit 1
    fi
fi

# Ensure uv is in PATH for this session
export PATH="$UV_INSTALL_DIR:$PATH"

# Verify uv works
if ! uv --version &> /dev/null; then
    echo "Error: uv installation failed."
    exit 1
fi
echo "uv version: $(uv --version)"

# --- Python Dependencies ---
echo ""
echo "--- [6/6] Installing Python dependencies ---"

cd "$SCRIPT_DIR"

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    uv venv
fi

# Install from local wheels
if [ -d "$WHEELS_DIR" ] && [ "$(ls -A "$WHEELS_DIR"/*.whl 2>/dev/null)" ]; then
    WHEEL_COUNT=$(ls -1 "$WHEELS_DIR"/*.whl 2>/dev/null | wc -l)
    echo "Installing from $WHEEL_COUNT local wheels..."

    # Install using uv with offline mode and local wheel directory
    uv pip install \
        --offline \
        --find-links "$WHEELS_DIR" \
        --python .venv/bin/python \
        -r <(uv export --frozen --no-hashes 2>/dev/null | grep -v "tetra3" || cat << 'DEPS'
plotly>=5.0.0
pyserial>=3.5
pynmea2>=1.19.0
astropy>=6.0.1
fitsio>=1.2.0
matplotlib>=3.9.4
numcodecs>=0.12.0
numpy>=1.26.4
pillow>=11.2.1
scipy>=1.13.1
tqdm>=4.67.1
zarr>=2.18.0
zwoasi>=0.2.0
DEPS
) 2>&1 || {
        echo "Warning: Some packages may have failed to install."
    }
else
    echo "Warning: No wheels found in $WHEELS_DIR"
    echo "Attempting to install from existing cache..."
    uv sync --offline 2>/dev/null || {
        echo "Error: Could not install Python dependencies offline."
        exit 1
    }
fi

# Install tetra3 from local submodule
echo "Installing tetra3 from local submodule..."
TETRA3_DIR="$SCRIPT_DIR/asi_driver/tetra3"

# Check if tetra3 wheel exists in offline packages
TETRA3_WHEEL=$(ls "$WHEELS_DIR"/tetra3*.whl 2>/dev/null | head -1)
if [ -n "$TETRA3_WHEEL" ]; then
    echo "Installing tetra3 from pre-built wheel..."
    uv pip install --offline --find-links "$WHEELS_DIR" --python .venv/bin/python "$TETRA3_WHEEL"
elif [ -d "$TETRA3_DIR" ]; then
    echo "Installing tetra3 from submodule (editable)..."
    uv pip install --offline --find-links "$WHEELS_DIR" --python .venv/bin/python -e "$TETRA3_DIR" 2>/dev/null || {
        # Fallback: try without --offline for editable install
        uv pip install --find-links "$WHEELS_DIR" --python .venv/bin/python -e "$TETRA3_DIR" --no-index 2>/dev/null || {
            echo "Warning: Could not install tetra3. Some features may not work."
        }
    }
else
    echo "Warning: tetra3 not found. Some features may not work."
fi

# Install the main package in editable mode
echo "Installing main package..."
uv pip install --offline --find-links "$WHEELS_DIR" --python .venv/bin/python -e . 2>/dev/null || {
    uv pip install --find-links "$WHEELS_DIR" --python .venv/bin/python -e . --no-index 2>/dev/null || {
        echo "Warning: Could not install main package in editable mode."
    }
}

# --- Summary ---
echo ''
echo '=== Offline Installation Complete ==='
echo ''
echo 'NOTE: Log out and back in for dialout group permissions to take effect.'
echo ''
echo 'To activate the Python environment:'
echo '  source .venv/bin/activate'
echo ''
echo 'To verify installation:'
echo '  python -c "import tetra3; import zwoasi; import astropy; print('\''All imports OK'\'')"'
echo ''
echo 'To run the mount control:'
echo '  Terminal 1: ./start_server.sh'
echo '  Terminal 2: python mount_driver/point_mount.py'
echo ''
echo 'To run ASI camera commands:'
echo '  asi-focus, asi-burst, asi-gps-test, asi-cam-setup'
echo ''
