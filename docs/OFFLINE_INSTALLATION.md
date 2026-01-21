# Offline Installation Guide

This guide explains how to install the Satellite Observation System on machines without internet access.

## Overview

The offline installation process uses a two-script workflow:

1. **`prepare_offline_packages.sh`** - Run on an internet-connected machine to download all dependencies
2. **`install_offline.sh`** or **`install_dependencies.sh --offline`** - Run on the offline target machine

## Prerequisites

### Preparation Machine (Internet-Connected)
- Ubuntu (same version as target machine)
- Same CPU architecture as target machine (x86_64 or aarch64)
- Git installed
- ~2GB free disk space for downloaded packages

### Target Machine (Offline)
- Ubuntu (same version as preparation machine)
- Same CPU architecture as preparation machine
- Sudo access (for APT packages and udev rules)

## Step-by-Step Instructions

### Step 1: Prepare Packages (On Internet-Connected Machine)

1. Clone the repository and navigate to it:
   ```bash
   git clone <repository-url>
   cd mermaids_experiment
   ```

2. Run the preparation script:
   ```bash
   ./prepare_offline_packages.sh
   ```

   This will:
   - Download all APT packages (INDI, dependencies)
   - Download the uv package manager binary
   - Download all Python wheels
   - Build the tetra3 wheel from the local submodule
   - Create a manifest file with version information

3. Verify the offline packages were created:
   ```bash
   ls -la offline_packages/
   cat offline_packages/manifest.json
   ```

### Step 2: Transfer to Offline Machine

Copy the entire project directory (including `offline_packages/`) to your offline machine. If working on the same machine skip this step.

```bash
# Option 1: USB drive
cp -r mermaids_experiment /media/usb_drive/

# Option 2: tar archive
tar -czvf mermaids_offline.tar.gz mermaids_experiment/
# Then transfer mermaids_offline.tar.gz to the target machine
```

**Important:** Ensure the entire `offline_packages/` directory is included in the transfer.

### Step 3: Install on Offline Machine

1. Extract or copy the project to the target machine
2. Navigate to the project directory:
   ```bash
   cd mermaids_experiment
   ```

3. Run the installation:
   ```bash
   ./install_dependencies.sh --offline
   # Or equivalently:
   ./install_offline.sh
   ```

4. Log out and back in for group permissions to take effect

### Step 4: Verify Installation

```bash
# Activate the Python environment
source .venv/bin/activate

# Test Python imports
python -c "import tetra3; import zwoasi; import astropy; print('All imports OK')"

# Verify INDI is installed
which indiserver
indiserver --help

# Verify udev rules
ls /etc/udev/rules.d/asi.rules
```

## Directory Structure

After running `prepare_offline_packages.sh`, the following structure is created:

```
offline_packages/
├── apt/
│   └── {ubuntu_codename}/      # e.g., jammy/, noble/
│       └── *.deb               # All .deb files + dependencies
├── python/
│   └── wheels/
│       └── *.whl               # All Python wheels
├── uv/
│   └── uv                      # Pre-downloaded uv binary
└── manifest.json               # Version info and metadata
```

## Installation Modes

The main `install_dependencies.sh` script supports three modes:

| Command | Behavior |
|---------|----------|
| `./install_dependencies.sh` | Auto-detect (uses offline if packages exist and no internet) |
| `./install_dependencies.sh --offline` | Force offline mode |
| `./install_dependencies.sh --online` | Force online mode |

## Troubleshooting

### Architecture Mismatch
```
Error: Packages prepared for x86_64, but running on aarch64
```
**Solution:** Prepare packages on a machine with the same CPU architecture as the target.

### Ubuntu Version Mismatch
```
Warning: Packages prepared for Ubuntu jammy, but running on noble
```
**Solution:** Prepare packages on a machine with the same Ubuntu version. APT packages are version-specific.

### Missing Dependencies
```
dpkg: dependency problems prevent configuration of indi-bin
```
**Solution:** Some system packages may not have been included. If the target machine has some packages already installed, the installation may still succeed. Otherwise, prepare packages on a clean Ubuntu installation.

### tetra3 Import Error
```
ModuleNotFoundError: No module named 'tetra3'
```
**Solution:** Ensure the git submodules were properly initialized before preparing packages:
```bash
git submodule update --init --recursive
cd asi_driver && git checkout dev && cd ..
```

### uv Not Found
```
Error: uv is required but not available
```
**Solution:** The uv binary should be in `offline_packages/uv/uv`. Verify the preparation step completed successfully.

## Size Estimates

Typical `offline_packages/` sizes:

| Component | Approximate Size |
|-----------|------------------|
| APT packages | 300-500 MB |
| Python wheels | 200-400 MB |
| uv binary | ~15 MB |
| **Total** | **500 MB - 1 GB** |

## Notes

- **No Mount Testing:** Do NOT run `point_mount.py` unless mounts are properly configured. Attempting to slew unconfigured mounts can cause physical damage.

- **Submodules:** Git submodules (tetra3, asi_driver) must be fully initialized before preparing offline packages. The submodule directories must be included when copying to the offline machine.

- **Python Version:** The offline packages are prepared for Python 3.12. If your target system uses a different Python version, you may need to re-prepare the packages.
