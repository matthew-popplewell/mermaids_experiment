#!/bin/bash
# prepare_offline_packages.sh
# Downloads all dependencies for offline installation.
# Run this on an internet-connected machine with the same architecture and Ubuntu version
# as your target offline machine.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OFFLINE_DIR="$SCRIPT_DIR/offline_packages"

# Detect system info
UBUNTU_CODENAME=$(lsb_release -cs 2>/dev/null || echo "unknown")
ARCH=$(uname -m)
if [ "$ARCH" = "x86_64" ]; then
    PYTHON_PLATFORM="manylinux_2_17_x86_64"
    UV_PLATFORM="x86_64-unknown-linux-gnu"
elif [ "$ARCH" = "aarch64" ]; then
    PYTHON_PLATFORM="manylinux_2_17_aarch64"
    UV_PLATFORM="aarch64-unknown-linux-gnu"
else
    echo "Error: Unsupported architecture: $ARCH"
    exit 1
fi

echo "=== Preparing Offline Packages ==="
echo "Ubuntu codename: $UBUNTU_CODENAME"
echo "Architecture: $ARCH"
echo "Output directory: $OFFLINE_DIR"
echo ""

# Create directory structure
mkdir -p "$OFFLINE_DIR/apt/$UBUNTU_CODENAME"
mkdir -p "$OFFLINE_DIR/python/wheels"
mkdir -p "$OFFLINE_DIR/uv"

# --- APT Packages ---
echo "--- [1/4] Downloading APT packages ---"

APT_DIR="$OFFLINE_DIR/apt/$UBUNTU_CODENAME"
APT_PACKAGES="indi-bin indi-eqmod python3-indi-client libindi-dev libusb-1.0-0-dev libcfitsio-dev"

# First, ensure the PPA is added so we can resolve dependencies
if ! grep -q "mutlaqja/ppa" /etc/apt/sources.list.d/*.list 2>/dev/null; then
    echo "Adding INDI PPA..."
    sudo apt-add-repository ppa:mutlaqja/ppa -y
    sudo apt-get update
fi

# Get all dependencies recursively
echo "Resolving dependencies for: $APT_PACKAGES"
DEPS=$(apt-cache depends --recurse --no-recommends --no-suggests --no-conflicts \
    --no-breaks --no-replaces --no-enhances $APT_PACKAGES 2>/dev/null | \
    grep "^\w" | grep -v "^<" | sort -u)

echo "Found $(echo "$DEPS" | wc -w) packages to download"

# Download packages
cd "$APT_DIR"
echo "Downloading packages to $APT_DIR..."
for pkg in $DEPS; do
    if ! apt-get download "$pkg" 2>/dev/null; then
        echo "  Warning: Could not download $pkg (may be virtual or already satisfied)"
    fi
done
cd "$SCRIPT_DIR"

DEB_COUNT=$(ls -1 "$APT_DIR"/*.deb 2>/dev/null | wc -l)
echo "Downloaded $DEB_COUNT .deb files"

# --- uv Package Manager ---
echo ""
echo "--- [2/4] Downloading uv binary ---"

UV_VERSION=$(curl -sL https://api.github.com/repos/astral-sh/uv/releases/latest | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/')
if [ -z "$UV_VERSION" ]; then
    echo "Warning: Could not determine latest uv version, using 0.5.14"
    UV_VERSION="0.5.14"
else
    # Remove 'v' prefix if present for URL construction
    UV_VERSION="${UV_VERSION#v}"
fi

UV_URL="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-${UV_PLATFORM}.tar.gz"
echo "Downloading uv $UV_VERSION from: $UV_URL"

curl -LsSf "$UV_URL" -o "$OFFLINE_DIR/uv/uv.tar.gz"
tar -xzf "$OFFLINE_DIR/uv/uv.tar.gz" -C "$OFFLINE_DIR/uv/"
# The binary is extracted to a subdirectory, move it up
if [ -f "$OFFLINE_DIR/uv/uv-${UV_PLATFORM}/uv" ]; then
    mv "$OFFLINE_DIR/uv/uv-${UV_PLATFORM}/uv" "$OFFLINE_DIR/uv/"
    mv "$OFFLINE_DIR/uv/uv-${UV_PLATFORM}/uvx" "$OFFLINE_DIR/uv/" 2>/dev/null || true
    rm -rf "$OFFLINE_DIR/uv/uv-${UV_PLATFORM}"
fi
rm -f "$OFFLINE_DIR/uv/uv.tar.gz"
chmod +x "$OFFLINE_DIR/uv/uv"

echo "uv binary saved to: $OFFLINE_DIR/uv/uv"

# --- Python Wheels ---
echo ""
echo "--- [3/4] Downloading Python wheels ---"

WHEELS_DIR="$OFFLINE_DIR/python/wheels"

# Ensure uv is available (either installed or just downloaded)
if command -v uv &> /dev/null; then
    UV_CMD="uv"
else
    UV_CMD="$OFFLINE_DIR/uv/uv"
fi

# Initialize git submodules if needed
if [ ! -d "$SCRIPT_DIR/asi_driver/tetra3/tetra3" ]; then
    echo "Initializing git submodules..."
    cd "$SCRIPT_DIR"
    git submodule update --init --recursive
    cd asi_driver && git checkout dev && cd ..
fi

# Create a temporary requirements file excluding tetra3 (we'll build it locally)
echo "Exporting Python dependencies..."
TEMP_REQUIREMENTS=$(mktemp)

# Export from uv.lock, filtering out tetra3
$UV_CMD export --frozen --no-hashes 2>/dev/null | grep -v "tetra3" > "$TEMP_REQUIREMENTS" || {
    # Fallback: extract from pyproject.toml
    echo "plotly>=5.0.0
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
hatchling" > "$TEMP_REQUIREMENTS"
}

# Add build dependencies
echo "hatchling" >> "$TEMP_REQUIREMENTS"
echo "wheel" >> "$TEMP_REQUIREMENTS"
echo "pip" >> "$TEMP_REQUIREMENTS"

echo "Downloading wheels for Python packages..."
$UV_CMD pip download \
    -r "$TEMP_REQUIREMENTS" \
    --dest "$WHEELS_DIR" \
    --python-version 3.12 \
    --platform "$PYTHON_PLATFORM" \
    --platform linux_x86_64 \
    --platform any \
    2>&1 | grep -v "already downloaded" || true

rm -f "$TEMP_REQUIREMENTS"

# Build tetra3 wheel from local submodule
echo ""
echo "--- [4/4] Building tetra3 wheel from submodule ---"

TETRA3_DIR="$SCRIPT_DIR/asi_driver/tetra3"
if [ -d "$TETRA3_DIR" ]; then
    echo "Building wheel for tetra3..."
    cd "$TETRA3_DIR"
    # Use pip to build wheel (uv doesn't have build command)
    $UV_CMD pip wheel . --no-deps --wheel-dir "$WHEELS_DIR" 2>/dev/null || {
        # Fallback: use python directly
        python3 -m pip wheel . --no-deps --wheel-dir "$WHEELS_DIR" 2>/dev/null || {
            echo "Warning: Could not build tetra3 wheel. Will install from submodule during offline install."
        }
    }
    cd "$SCRIPT_DIR"
else
    echo "Warning: tetra3 submodule not found at $TETRA3_DIR"
    echo "Run 'git submodule update --init --recursive' first"
fi

WHEEL_COUNT=$(ls -1 "$WHEELS_DIR"/*.whl 2>/dev/null | wc -l)
echo "Total wheels downloaded/built: $WHEEL_COUNT"

# --- Create manifest ---
echo ""
echo "--- Creating manifest.json ---"

cat > "$OFFLINE_DIR/manifest.json" << EOF
{
    "created": "$(date -Iseconds)",
    "ubuntu_codename": "$UBUNTU_CODENAME",
    "architecture": "$ARCH",
    "uv_version": "$UV_VERSION",
    "apt_packages": $DEB_COUNT,
    "python_wheels": $WHEEL_COUNT,
    "source_commit": "$(git rev-parse HEAD 2>/dev/null || echo 'unknown')"
}
EOF

# --- Summary ---
echo ""
echo "=== Offline Package Preparation Complete ==="
echo ""
echo "Directory structure:"
find "$OFFLINE_DIR" -type d | head -20 | sed 's/^/  /'
echo ""
echo "Total size: $(du -sh "$OFFLINE_DIR" | cut -f1)"
echo ""
echo "Package counts:"
echo "  APT packages (.deb): $DEB_COUNT"
echo "  Python wheels (.whl): $WHEEL_COUNT"
echo "  uv binary: $([ -f "$OFFLINE_DIR/uv/uv" ] && echo 'Yes' || echo 'No')"
echo ""
echo "Next steps:"
echo "  1. Copy the entire project directory to your offline machine"
echo "  2. Run: ./install_dependencies.sh --offline"
echo "  3. Or run: ./install_offline.sh"
echo ""
