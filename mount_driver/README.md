# Star Adventurer GTi Mount Control

Command one or multiple co-located Sky-Watcher Star Adventurer GTi mounts to point at specific Azimuth/Elevation coordinates using Python and INDI on Linux.

## Overview

This system uses the INDI (Instrument Neutral Distributed Interface) protocol to communicate with Star Adventurer GTi mounts over USB. The mount's built-in GoTo functionality is used to slew both the RA and DEC axes to achieve the desired pointing direction.

**Key Capabilities:**

Single mount:
```bash
./point_mount.py goto 90 45    # Point to Az=90, El=45
```

Multiple mounts (all point to same location):
```bash
./multi_mount.py goto 90 45    # All mounts point to Az=90, El=45
```

## Hardware Requirements

- One or more Sky-Watcher Star Adventurer GTi mounts
- 12V DC power supply for each mount
- USB cables (one per mount)
- Linux computer (Ubuntu 22.04 or newer recommended)
- USB hub (recommended for multiple mounts)
- USB GPS receiver (optional, for automatic location detection)

## Software Installation

### Step 1: Install Dependencies

```bash
chmod +x install_dependencies.sh
./install_dependencies.sh
```

This installs:
- INDI server and client tools
- Star Adventurer GTi telescope driver
- Python 3.10
- GPS support (pyserial, pynmea2 for direct serial connection)

**Important:** After installation, log out and log back in for serial port permissions to take effect.

### Step 2: Verify Installation

```bash
ls /usr/bin/indi_*telescope*
```

You should see `indi_staradventurergti_telescope` in the list.

## Hardware Setup

### Connecting the Mounts

1. Connect 12V power to each mount
2. Connect USB cable from each mount to the computer (use a powered USB hub for multiple mounts)
3. Power on all mounts

### Verifying Connections

```bash
python3 diagnose.py
```

This shows:
- Number of USB devices detected
- Serial numbers for each mount
- INDI connection status

## Physical Mount Alignment

For accurate Az/El pointing, each mount must be physically aligned.

### Step 1: Level the Tripod(s)

Use a bubble level to ensure each tripod is level.

### Step 2: Polar Alignment

Each mount's RA axis must point toward the celestial pole.

**Northern Hemisphere:**
1. Point the mount's polar axis toward Polaris
2. Set the latitude scale to match your location
3. Use the polar scope for fine adjustment

### Step 3: Set Home Position

For each mount:
1. Rotate so the counterweight bar points straight down
2. The mounting platform should be roughly level

## Single Mount Operation

Use `point_mount.py` for controlling a single mount.

### Start the INDI Server

```bash
./start_server.sh
```

Keep this terminal open.

### Set Location and Calibrate

Set location manually:
```bash
./point_mount.py set-location 36.17 -115.14    # Your lat/lon
```

Or use a USB GPS receiver for automatic location (connects directly, no daemon required):
```bash
./point_mount.py gps-location                   # Auto-detect GPS and read location
./point_mount.py gps-location --wait 60         # Longer timeout if needed
./point_mount.py gps-location --port /dev/ttyUSB0  # Specify GPS port manually
```

Then calibrate:
```bash
./point_mount.py sync 0 45                      # Sync to known position
```

### Command the Mount

```bash
./point_mount.py goto 90 45    # Point to Az=90, El=45
```

## Multi-Mount Operation

Use `multi_mount.py` for controlling multiple co-located mounts.

### Start the INDI Server for Multiple Mounts

```bash
./start_server.sh 4    # Start with 4 mount instances
```

Or let it auto-detect:
```bash
./start_server.sh      # Auto-detects number of connected mounts
```

Mounts will appear as "Mount 1", "Mount 2", etc.

### Check Status

```bash
./multi_mount.py status
```

Shows all discovered mounts and their connection status.

### Set Location (Shared by All Mounts)

Since mounts are co-located, they share the same geographic location.

Set manually:
```bash
./multi_mount.py set-location 36.17 -115.14
```

Or use GPS (connects directly, no daemon required):
```bash
./multi_mount.py gps-location                   # Auto-detect GPS and read location
./multi_mount.py gps-location --port /dev/ttyUSB0  # Specify GPS port manually
```

### Calibrate Each Mount

Each mount needs to be calibrated individually. Point each mount at a known reference and sync:

```bash
# Calibrate Mount 1
./multi_mount.py sync 0 45 --mount 1

# Calibrate Mount 2
./multi_mount.py sync 0 45 --mount 2

# Calibrate Mount 3
./multi_mount.py sync 0 45 --mount 3

# etc.
```

### Command All Mounts to Same Position

```bash
./multi_mount.py goto 90 45    # All mounts slew to Az=90, El=45
```

The mounts slew in parallel and the command waits for all to complete.

### Command a Specific Mount

```bash
./multi_mount.py goto 90 45 --mount 2    # Only Mount 2 slews
```

### Emergency Stop

```bash
./multi_mount.py stop    # Stops ALL mounts immediately
```

## Command Reference

### Single Mount (point_mount.py)

| Command | Description |
|---------|-------------|
| `./point_mount.py` | Show current position |
| `./point_mount.py goto AZ EL` | Slew to Az/El coordinates |
| `./point_mount.py sync AZ EL` | Calibrate mount |
| `./point_mount.py set-location LAT LON` | Set location manually |
| `./point_mount.py gps-location` | Set location from GPS |
| `./point_mount.py gps-location --wait N` | GPS with N second timeout |
| `./point_mount.py gps-location --port DEV` | GPS with specific port |
| `./point_mount.py status` | Show detailed status |
| `./point_mount.py stop` | Emergency stop |

### Multiple Mounts (multi_mount.py)

| Command | Description |
|---------|-------------|
| `./multi_mount.py` | Show status of all mounts |
| `./multi_mount.py goto AZ EL` | Slew ALL mounts to Az/El |
| `./multi_mount.py goto AZ EL --mount N` | Slew only Mount N |
| `./multi_mount.py sync AZ EL` | Sync ALL mounts |
| `./multi_mount.py sync AZ EL --mount N` | Sync only Mount N |
| `./multi_mount.py set-location LAT LON` | Set location manually |
| `./multi_mount.py gps-location` | Set location from GPS |
| `./multi_mount.py gps-location --port DEV` | GPS with specific port |
| `./multi_mount.py assign` | Interactive port assignment |
| `./multi_mount.py stop` | Emergency stop ALL mounts |

## Quick Start Checklist

### Single Mount

1. [ ] Install: `./install_dependencies.sh`
2. [ ] Connect and power mount
3. [ ] Level tripod, polar align
4. [ ] Start server: `./start_server.sh`
5. [ ] Set location: `./point_mount.py set-location LAT LON`
6. [ ] Calibrate: `./point_mount.py sync AZ EL`
7. [ ] Command: `./point_mount.py goto AZ EL`

### Multiple Mounts

1. [ ] Install: `./install_dependencies.sh`
2. [ ] Connect and power all mounts
3. [ ] Level tripods, polar align each mount
4. [ ] Start server: `./start_server.sh N` (N = number of mounts)
5. [ ] Check status: `./multi_mount.py status`
6. [ ] Set location: `./multi_mount.py set-location LAT LON`
7. [ ] Calibrate each: `./multi_mount.py sync AZ EL --mount 1` (repeat for each)
8. [ ] Command all: `./multi_mount.py goto AZ EL`

## File Descriptions

| File | Purpose |
|------|---------|
| `point_mount.py` | Single mount control |
| `multi_mount.py` | Multiple mount control |
| `gps_serial.py` | Direct serial GPS reader |
| `start_server.sh` | Starts INDI server (single or multi) |
| `install_dependencies.sh` | Installs required software |
| `diagnose.py` | Diagnostic tool |
| `.mount_config.json` | Single mount config |
| `.multi_mount_config.json` | Multi-mount config |

## Troubleshooting

### Mounts not detected

```bash
python3 diagnose.py
```

Check:
- All mounts powered on
- USB cables connected
- Try different USB ports

### Mounts connect to wrong ports

Use the assign command to manually assign ports:
```bash
./multi_mount.py assign
```

### One mount points wrong direction

Recalibrate that specific mount:
```bash
./multi_mount.py sync AZ EL --mount N
```

### Permission denied on serial port

```bash
sudo usermod -a -G dialout $USER
```
Then log out and back in.

### INDI server not running

```bash
./start_server.sh    # Single mount
./start_server.sh 4  # Four mounts
```

### GPS not working

**GPS not detected:**
```bash
# List available serial ports
ls -la /dev/ttyUSB* /dev/ttyACM*

# Try specifying the port manually
./point_mount.py gps-location --port /dev/ttyUSB0
./point_mount.py gps-location --port /dev/ttyACM0
```

**Permission denied:**
```bash
# Add user to dialout group
sudo usermod -a -G dialout $USER
# Then log out and back in
```

**No satellite fix:**
- Move to a location with clear sky view
- Wait longer: `./point_mount.py gps-location --wait 120`
- GPS receivers can take several minutes to get first fix

**Missing Python packages:**
```bash
pip install pyserial pynmea2
```

## Technical Details

### Mount Naming

- Single mount mode: "Star Adventurer GTi"
- Multi-mount mode: "Mount 1", "Mount 2", etc.

### USB Identification

Each mount has a unique USB serial number. The system auto-detects connected mounts by scanning `/dev/ttyACM*` devices.

### Parallel Operation

When commanding multiple mounts, GoTo commands are sent in parallel using thread pools. The system waits for all mounts to complete before returning.

### Coordinate System

- Azimuth: 0-360 degrees (0=North, 90=East, 180=South, 270=West)
- Elevation: -90 to +90 degrees (0=horizon, 90=zenith)

## Stopping the System

1. Stop all mounts: `./multi_mount.py stop`
2. Stop INDI server: Ctrl+C in server terminal
3. Power off mounts
