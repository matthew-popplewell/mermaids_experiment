# MERMAIDS Operations Guide

A comprehensive guide for operating the MERMAIDS multi-mount telescope array with ZWO ASI cameras.

## Table of Contents

1. [System Overview](#system-overview)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
4. [Daily Operations Workflow](#daily-operations-workflow)
5. [Command Reference](#command-reference)
6. [Troubleshooting](#troubleshooting)
7. [Data Output](#data-output)

---

## System Overview

### Hardware Components

| Component | Description |
|-----------|-------------|
| **Mounts** | 4x Star Adventurer GTi equatorial mounts |
| **Cameras** | 4x ZWO ASI cameras (one per mount) |
| **GPS** | USB GPS receiver (Adafruit Ultimate GPS or similar) |
| **Computer** | Linux system with USB connections to all devices |

### Software Architecture

```
mermaids/
├── mount_driver/          # Mount control package
│   ├── mount.py          # Single mount control
│   ├── multi_mount.py    # Multi-mount coordination
│   ├── pointing_model.py # Polar misalignment correction
│   ├── calibration.py    # Plate solving calibration
│   ├── gps.py            # GPS location services
│   └── cli/              # Command-line interfaces
│
├── asi_driver/            # Camera control package
│   └── src/asi_driver/
│       ├── camera.py     # Camera control
│       ├── capture.py    # Image capture
│       └── cli/          # Camera CLI commands
│
└── scripts/
    └── start_server.sh   # INDI server startup
```

---

## Installation

### Prerequisites

- Ubuntu 22.04+ or similar Linux distribution
- Python 3.11+
- INDI server and Star Adventurer GTi driver
- USB access to mounts, cameras, and GPS

### Install Steps

See [OFFLINE_INSTALLATION.md](../OFFLINE_INSTALLATION.md) for detailed offline installation instructions.

Quick install (with internet):

```bash
# Create virtual environment
uv venv --python 3.11
source .venv/bin/activate

# Install package
uv sync
```

### Verify Installation

```bash
# Check CLI commands are available
mount-single --help
mount-multi --help
mount-calibrate --help
mount-diagnose --help
mount-observe --help

asi-focus --help
asi-burst --help
```

---

## Quick Start

Minimal commands to get running:

```bash
# 1. Start INDI server (auto-detects mounts)
./scripts/start_server.sh

# 2. Check system status
mount-diagnose

# 3. Get GPS location
mount-multi gps-location

# 4. Verify mount clock (sync if off by >1 min)
mount-multi check-time
mount-multi sync-time      # Only if check-time shows offset

# 5. Point all mounts to target
mount-multi goto 90 45    # Az=90, El=45

# 6. Run burst capture
asi-burst -d 60 -o ./data/ --cameras 1,2,3,4 --no-solve
```

---

## Daily Operations Workflow

### 1. Hardware Setup

1. **Power on mounts**: Connect 12V power to each Star Adventurer GTi
2. **USB connections**: Connect all mounts to USB hub
3. **Camera connections**: Connect all ZWO cameras to USB
4. **GPS receiver**: Connect USB GPS receiver
5. **Verify connections**: Check all USB devices are detected

```bash
# Check USB devices
ls /dev/ttyACM*  # Mounts
ls /dev/ttyUSB*  # GPS (may also be ttyACM)
```

### 2. Start INDI Server

```bash
# Auto-detect and start all mounts
./scripts/start_server.sh

# Or specify number of mounts explicitly
./scripts/start_server.sh 4
```

The server will:
- Start INDI server with mount drivers
- Auto-connect mounts to USB ports
- Keep running in foreground (Ctrl+C to stop)

### 3. Set Location from GPS
In new terminal:

```bash
# Get GPS fix and apply to all mounts
mount-multi gps-location

# Or set manually
mount-multi set-location 39.917506 -105.002898
```

### 3b. Verify Mount Clock

The mounts derive LST (Local Sidereal Time) from their internal clock. If the clock is wrong, all Az/El → RA/DEC conversions will be off (1 minute of time error ≈ 0.25° pointing error).

```bash
# Check mount time against system clock
mount-multi check-time

# If off by more than 1 minute, sync from system clock
mount-multi sync-time
```

The `goto` command also prints an automatic warning if the mount clock is off by more than 1 minute.

### 3c. Camera-Mount Pairing

Each mount has a paired camera for plate solving. Camera indices (0, 1, 2, 3) are assigned by the ZWO SDK based on USB enumeration order — this can change across reboots. For reliable pairing, assign persistent IDs stored in camera firmware:

```bash
# List cameras and current IDs
asi-cam-setup --list

# Assign IDs (identify cameras by covering lenses one at a time)
asi-cam-setup --index 0 --set-id 1    # Stores "CAM_1" in firmware
asi-cam-setup --index 1 --set-id 2    # Stores "CAM_2"
asi-cam-setup --index 2 --set-id 3
asi-cam-setup --index 3 --set-id 4

# Store mount-camera pairing in config
mount-multi set-camera-map 1 CAM_1 2 CAM_2 3 CAM_3 4 CAM_4

# Verify
mount-multi show-camera-map
```

Once configured, all plate-solving commands (`calibrate-pointing --auto`, `goto-solve`, `mount-calibrate --all`) automatically use the correct camera for each mount. You can still override with `--camera CAM_X` or `--camera-index N`.

Camera IDs only need to be set once (they survive power cycles). The camera map in config persists across sessions.

### 4. Polar Alignment (Physical)

Before calibrating, physically align mounts:

1. Level the tripod
2. Point mount axis toward Polaris (northern hemisphere)
3. Use built-in polar scope if available
4. Fine-tune using drift alignment or electronic polar alignment

### 5. Calibrate via Plate Solving

```bash
# Calibrate all mounts using their paired cameras
mount-calibrate --all

# Or calibrate specific mount
mount-calibrate --mount 1 --camera CAM_1
```

This will:
- Capture an image with each camera
- Plate solve to determine actual sky position
- Sync each mount to match the solution

### 5b. Calibrate manually (if plate solving fails)
```bash
mount-multi sync AZ EL
```

### 5c. Pointing Model Calibration

Even with a sync, mounts that are only roughly polar aligned (5-15° off) will have growing GoTo errors as they slew away from the sync point. The pointing model corrects for this by measuring the polar misalignment and applying a per-mount correction to all future GoTo commands.

**Option A: Auto-calibrate with plate solving (preferred)**

Fully automated — slews to 3 targets and plate solves each to measure actual position:

```bash
# Auto-calibrate using camera (mount 1 paired with camera index 0)
mount-multi calibrate-pointing --auto --mount 1

# Specify camera explicitly
mount-multi calibrate-pointing --auto --mount 2 --camera-index 1

# Adjust exposure/gain for conditions
mount-multi calibrate-pointing --auto --mount 1 --exposure 1.0 --gain 100
```

**Option B: Manual calibration with phone**

If plate solving is unavailable (no camera, daytime, etc.):

```bash
mount-multi calibrate-pointing --mount 1
```

**Manage models:**

```bash
# Show current calibration for all mounts
mount-multi calibrate-pointing --show

# Clear calibration for a mount
mount-multi calibrate-pointing --clear --mount 1
```

**How it works:**
1. Sync the mount to its current position first (step 5b)
2. Run calibration (auto or manual)
3. Mount slews to 3 spread-out targets (Az=90/El=45, Az=180/El=50, Az=270/El=45)
4. At each target, the actual position is measured (plate solve or phone)
5. Code solves for the polar misalignment parameters (ME/MA) and saves them
6. All future GoTo commands automatically apply the correction

The calibration only needs to be redone if the mount is physically moved or re-aligned. Re-syncing does not invalidate the model.

### 5d. Closed-Loop GoTo (alternative to calibration)

Instead of pre-calibrating, you can use plate solving to iteratively correct each goto in real-time. This is slower (requires capture+solve per iteration) but doesn't need any prior calibration:

```bash
# Goto with plate-solve verification loop
mount-multi goto-solve 90 45 --mount 1

# Tighter tolerance (default 1 degree)
mount-multi goto-solve 180 50 --mount 1 --tolerance 0.5

# Adjust plate solving parameters
mount-multi goto-solve 90 45 --mount 1 --exposure 1.0 --gain 100 --fov 10
```

The closed-loop goto will:
1. Slew to target Az/El
2. Plate solve to check actual position
3. If error > tolerance, adjust and re-slew
4. Repeat until on-target (up to 5 iterations)

This works well for one-off pointings. For repeated gotos, calibrate the pointing model first — it's faster since corrections are pre-computed.

### 6. Point All Mounts

```bash
# Slew all mounts to target Az/El
mount-multi goto 90 45

# Check positions
mount-multi status
```

### 7. Focus Cameras

```bash
# Interactive focus adjustment
asi-focus --camera 0
```

Repeat for each camera, adjusting focus until stars are sharp.

### 8. Burst Capture

```bash
# Capture 60 seconds of data from all cameras
asi-burst -d 60 -o ./data/ --cameras 1,2,3,4

# With custom settings
asi-burst -d 300 -o ./data/ --cameras 1,2,3,4 \
    --exposure 20000 --gain 600 --binning 1
```

### Complete Workflow Command

For automated workflow:

```bash
# Run complete observation sequence
mount-observe --target 90 45 --duration 60 --output ./data/ --cameras 1,2,3,4
```

---

## Command Reference

### Mount Commands

#### `mount-single` - Single Mount Control

```bash
mount-single                              # Show current position
mount-single status                       # Detailed mount status
mount-single goto AZ EL                   # Slew to Az/El
mount-single goto-eq RA DEC               # Slew to RA/DEC (hours, degrees)
mount-single sync AZ EL                   # Sync to known Az/El
mount-single sync-eq RA DEC               # Sync to known RA/DEC
mount-single set-location LAT LON         # Set geographic location
mount-single gps-location                 # Get location from GPS
mount-single stop                         # Emergency stop
mount-single track                        # Live position tracking
mount-single calibrate-pointing           # Calibrate pointing model
mount-single calibrate-pointing --show    # Show model parameters
mount-single calibrate-pointing --clear   # Clear calibration
```

#### `mount-multi` - Multi-Mount Control

```bash
mount-multi status                          # Show all mounts
mount-multi connect                         # Auto-connect mounts
mount-multi goto AZ EL                      # Slew all mounts
mount-multi goto AZ EL --mount 1            # Slew specific mount
mount-multi sync AZ EL                      # Sync all mounts
mount-multi set-location LAT LON            # Set location for all
mount-multi gps-location                    # Get GPS location
mount-multi check-time                      # Compare mount clock vs system clock
mount-multi sync-time                       # Sync mount UTC from system clock
mount-multi set-camera-map 1 CAM_1 2 CAM_2  # Set mount-camera pairings
mount-multi show-camera-map                 # Show stored pairings
mount-multi stop                            # Emergency stop all
mount-multi calibrate-pointing --auto -m N  # Auto-calibrate (plate solving)
mount-multi calibrate-pointing --mount N    # Calibrate (phone measurements)
mount-multi calibrate-pointing --show       # Show model parameters
mount-multi calibrate-pointing --clear -m N # Clear mount's model
mount-multi goto-solve AZ EL --mount N      # Closed-loop goto (plate solving)
mount-multi debug AZ EL                     # Debug coordinate conversions
```

#### `mount-calibrate` - Plate Solving Calibration

```bash
mount-calibrate                   # Calibrate mount 1/camera 0
mount-calibrate --all             # Calibrate all mounts
mount-calibrate --verify          # Check calibration without syncing
mount-calibrate --dry-run         # Preview what would happen
mount-calibrate --mount 2 --camera CAM_2
mount-calibrate --exposure 1.0 --gain 100 --fov 8.0
```

#### `mount-diagnose` - System Diagnostics

```bash
mount-diagnose                    # Full system check
```

#### `mount-observe` - Complete Workflow

```bash
mount-observe --target AZ EL --duration SECS --output DIR
mount-observe --target 90 45 --duration 60 --output ./data/ --cameras 1,2,3,4
mount-observe --target 180 30 --duration 300 --output ./obs/ --skip-calibrate
```

Options:
- `--skip-gps`: Use saved location
- `--skip-calibrate`: Skip plate solving
- `--skip-focus`: Skip focus prompt
- `--skip-slew`: Assume already pointed

### Camera Commands

#### `asi-burst` - Burst Capture

```bash
asi-burst -d DURATION -o OUTPUT [options]

# Single camera
asi-burst -d 60 -o ./data/

# Multi-camera
asi-burst -d 60 -o ./data/ --cameras 1,2,3,4

# With plate solving
asi-burst -d 60 -o ./data/ --cameras 1,2,3,4 --fov 10

# Without plate solving (faster)
asi-burst -d 60 -o ./data/ --cameras 1,2,3,4 --no-solve
```

Options:
- `-d, --duration`: Capture duration in seconds
- `-o, --output`: Output directory
- `-e, --exposure`: Exposure time in microseconds (default: 20000)
- `-g, --gain`: Camera gain (default: 600)
- `-b, --binning`: Binning factor (default: 1)
- `--cameras`: Comma-separated camera IDs (e.g., 1,2,3,4)
- `--no-solve`: Skip plate solving
- `--fov`: Field of view estimate for plate solving
- `--format`: Output format (zarr, memmap, fits)

#### `asi-focus` - Focus Adjustment

```bash
asi-focus                         # Interactive focus mode
asi-focus --camera 0              # Specific camera
```

#### `asi-cam-setup` - Camera Setup

```bash
asi-cam-setup                     # Interactive camera configuration
```

---

## Troubleshooting

### No Mounts Detected

```bash
# Check USB devices
ls /dev/ttyACM*

# Run diagnostics
mount-diagnose
```

**Solutions:**
- Check mount power (12V connected)
- Check USB cable connections
- Try different USB port
- Check permissions: `sudo usermod -a -G dialout $USER`

### INDI Server Not Running

```bash
# Check server status
pgrep indiserver

# Restart server
./scripts/start_server.sh
```

### GPS Not Working

```bash
# Check GPS device
ls /dev/ttyUSB*

# Test GPS directly
mount-single gps-location --wait 120
```

**Solutions:**
- Move to location with clear sky view
- Wait longer for satellite fix
- Check GPS receiver LED indicators
- Try specifying port: `--port /dev/ttyUSB0`

### Plate Solving Fails

**Solutions:**
- Increase exposure: `--exposure 2.0`
- Check focus (stars should be sharp points)
- Verify camera is pointing at sky
- Check FOV estimate: `--fov 10`
- Try in darker conditions

### Large GoTo Pointing Errors (5-20°)

If the mount is synced but GoTo targets are off by 5-20°, the cause is polar misalignment. The one-star sync only corrects at the sync point; errors grow as the mount moves away.

**Solution:** Run pointing model calibration or use closed-loop goto:

```bash
# Option 1: Auto-calibrate with plate solving (best)
mount-multi calibrate-pointing --auto --mount N

# Option 2: Use closed-loop goto (no prior calibration needed)
mount-multi goto-solve 90 45 --mount N

# Option 3: Manual calibrate with phone (if no camera)
mount-multi calibrate-pointing --mount N
```

After calibration, verify by slewing to known positions. Errors should be within 1-2°.

If using `--auto` and the RMS is >2°, plate solving may be inconsistent. Ensure:
- Stars are visible and in focus
- Exposure is sufficient (try `--exposure 1.0`)
- FOV estimate is reasonable (try `--fov 8` or `--fov 12`)

### Consistent RA Offset (Mount Clock Wrong)

If the mount consistently points to the wrong RA (but DEC is correct), the mount's internal clock is likely wrong. The mount derives LST from its UTC clock — if the clock is off, all coordinate conversions are shifted in RA.

**Impact**: 1 minute of clock error ≈ 0.25° RA error. A 1-hour clock error causes 15° pointing error.

```bash
# Diagnose: compare mount time with system clock
mount-multi check-time

# Fix: sync mount UTC from computer's system clock
mount-multi sync-time

# Verify fix
mount-multi check-time
```

The `goto` command prints an automatic warning if the clock difference exceeds 1 minute.

**Note**: The INDI driver may or may not auto-sync the mount's clock on connection. If you see clock drift, run `mount-multi sync-time` at the start of each session.

### Wrong Camera Used for Plate Solving

If plate solving returns wrong positions or fails for specific mounts, the camera-mount pairing may be wrong.

```bash
# Check current pairing
mount-multi show-camera-map

# Re-configure (identify cameras by covering lenses)
asi-cam-setup --list
mount-multi set-camera-map 1 CAM_1 2 CAM_2 3 CAM_3 4 CAM_4
```

Without a stored camera map, the default pairing is mount N → camera index N-1, which depends on USB enumeration order and can change across reboots.

### Mount Won't Slew

```bash
# Check mount status
mount-multi status

# Emergency stop
mount-multi stop
```

**Solutions:**
- Verify location is set
- Check mount is connected (status shows "CONNECTED")
- Ensure target altitude is above horizon

---

## Data Output

### Output Directory Structure

After running `asi-burst`, data is saved as:

```
output_dir/
└── session_YYYYMMDD_HHMMSS/
    ├── exquisite_YYYYMMDD_HHMMSS.fits   # Plate solving image
    ├── burst_CAM_1_000.zarr/            # Burst data (zarr format)
    │   ├── frames/                       # Frame data
    │   └── timestamps/                   # Frame timestamps
    ├── burst_CAM_2_000.zarr/
    └── ...
```

### Reading Zarr Data

```python
import zarr
import numpy as np

# Open zarr store
store = zarr.open('burst_CAM_1_000.zarr', 'r')

# Get frames
frames = store['frames'][:]  # Shape: (n_frames, height, width)

# Get timestamps
timestamps = store['timestamps'][:]

# Read metadata
attrs = dict(store.attrs)
print(f"Camera: {attrs['camera_name']}")
print(f"Exposure: {attrs['exposure_us']} us")
```

### FITS Headers

Exquisite images include WCS headers when plate solving succeeds:

```python
from astropy.io import fits

with fits.open('exquisite_20240115_120000.fits') as hdul:
    header = hdul[0].header

    # WCS coordinates
    print(f"RA: {header['CRVAL1']}")
    print(f"DEC: {header['CRVAL2']}")
    print(f"FOV: {header['FOV']} degrees")

    # GPS location
    print(f"Lat: {header['SITELAT']}")
    print(f"Lon: {header['SITELONG']}")
```

---

## Tips for Best Results

1. **Polar alignment**: Rough alignment (within 15°) is fine if using pointing calibration
2. **Pointing calibration**: Run `calibrate-pointing --auto` once per session; only redo if mount is moved
3. **GPS fix**: Wait for 3D fix (4+ satellites) for best accuracy
4. **Mount clock**: Run `mount-multi check-time` after connecting; sync if off by >1 min
5. **Camera IDs**: Set firmware IDs once with `asi-cam-setup`; store pairing with `set-camera-map`
6. **Calibration order**: GPS location → sync time → camera map → sync → pointing calibration → GoTo
7. **Closed-loop vs model**: Use `goto-solve` for one-off pointings; use `calibrate-pointing --auto` for repeated gotos (faster after initial calibration)
8. **Focus**: Check focus periodically during long sessions
9. **Dark sky**: Plate solving works better with darker skies
10. **Cooling**: Let cameras stabilize temperature before capture

---

## Support

For issues and questions:
- Check [Troubleshooting](#troubleshooting) section
- Review INDI logs for mount errors
- Open issue at https://github.com/your-org/mermaids/issues
