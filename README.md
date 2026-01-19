# Star Adventurer GTi Mount Control

Command a Sky-Watcher Star Adventurer GTi mount to point at specific Azimuth/Elevation coordinates using Python and INDI on Linux.

## Overview

This system uses the INDI (Instrument Neutral Distributed Interface) protocol to communicate with the Star Adventurer GTi mount over USB. The mount's built-in GoTo functionality is used to slew both the RA and DEC axes to achieve the desired pointing direction.

**Key Capability:** Point the mount to any Az/El coordinate in the sky by running:
```bash
./point_mount.py goto <AZIMUTH> <ELEVATION>
```

## Hardware Requirements

- Sky-Watcher Star Adventurer GTi mount
- 12V DC power supply for the mount
- USB cable (Type-A to the mount's USB port)
- Linux computer (Ubuntu 22.04 or newer recommended)

## Software Installation

### Step 1: Install Dependencies

Run the installation script to install INDI drivers and required packages:

```bash
chmod +x install_dependencies.sh
./install_dependencies.sh
```

This installs:
- INDI server and client tools
- Star Adventurer GTi telescope driver (`indi_staradventurergti_telescope`)
- Python 3.10

**Important:** After installation, log out and log back in for serial port permissions to take effect.

### Step 2: Verify Installation

Check that the INDI driver is installed:

```bash
ls /usr/bin/indi_*telescope*
```

You should see `indi_staradventurergti_telescope` in the list.

## Hardware Setup

### Connecting the Mount

1. Connect the 12V power supply to the mount
2. Connect the USB cable between the mount and your computer
3. Power on the mount

### Verifying the Connection

Run the diagnostic tool to check that the mount is detected:

```bash
python3 diagnose.py
```

Expected output shows:
- USB device detected at `/dev/ttyACM0` (or similar)
- Device identified as "STM32 Virtual ComPort"

If no device is found:
- Check that the mount is powered on
- Try a different USB cable or port
- Verify the mount's power LED is on

## Physical Mount Alignment

For accurate Az/El pointing, the mount must be physically aligned before use.

### Step 1: Level the Tripod

Use a bubble level to ensure the tripod head is level. All three legs should be on stable ground.

### Step 2: Polar Alignment

The Star Adventurer GTi is an equatorial mount. Its RA (Right Ascension) axis must point toward the celestial pole for accurate coordinate conversion.

**Northern Hemisphere:**
1. Point the mount's polar axis toward Polaris (the North Star)
2. Set the latitude scale on the mount to match your latitude
3. Use the polar scope (if equipped) for fine adjustment

**Southern Hemisphere:**
1. Point the mount's polar axis toward the South Celestial Pole
2. The pole is near Sigma Octantis, but this star is faint

### Step 3: Set Home Position

Before powering on or after setup:
1. Rotate the mount so the counterweight bar points straight down (toward the ground)
2. The telescope/camera mounting platform should be roughly level

## Running the Mount Control System

### Step 1: Start the INDI Server

Open a terminal and start the INDI server. This must remain running while you control the mount.

```bash
./start_server.sh
```

The server will output connection information. Wait a few seconds for the mount to connect automatically.

**Keep this terminal open.** The server must stay running.

### Step 2: Set Your Geographic Location

In a second terminal, set your observer location. This is required for Az/El coordinate conversion.

```bash
./point_mount.py set-location <LATITUDE> <LONGITUDE>
```

**Example for Las Vegas:**
```bash
./point_mount.py set-location 36.17 -115.14
```

- Latitude: Positive for North, negative for South (-90 to +90)
- Longitude: Positive for East, negative for West (-180 to +180)

The location is saved and will be remembered for future sessions.

### Step 3: Calibrate the Mount (Sync)

The mount needs to know where it is currently pointing. Use the sync command to calibrate.

**Option A: Sync to a Known Star (Most Accurate)**

1. Manually point the mount at a bright star you can identify
2. Look up the star's RA and DEC coordinates
3. Sync the mount:

```bash
./point_mount.py sync-eq <RA_HOURS> <DEC_DEGREES>
```

**Example using Polaris (RA=2.53h, DEC=+89.26):**
```bash
# Point the mount at Polaris, then run:
./point_mount.py sync-eq 2.53 89.26
```

**Option B: Sync to a Known Az/El Direction**

If you know the exact Az/El you are pointing at (using a compass and inclinometer):

```bash
./point_mount.py sync <AZIMUTH> <ELEVATION>
```

**Example pointing due North at the horizon:**
```bash
./point_mount.py sync 0 0
```

**Option C: Sync to Polaris for Quick Northern Hemisphere Setup**

Polaris is almost exactly at the North Celestial Pole (Az=0, Alt=latitude):

```bash
# Point at Polaris, then sync to your latitude as the altitude
./point_mount.py sync 0 <YOUR_LATITUDE>
```

### Step 4: Verify Calibration

After syncing, verify the mount knows its position:

```bash
./point_mount.py status
```

The displayed Az/El should approximately match where the mount is physically pointing.

### Step 5: Command the Mount to Point

To slew the mount to a specific Azimuth and Elevation:

```bash
./point_mount.py goto <AZIMUTH> <ELEVATION>
```

**Coordinate System:**
- Azimuth: 0 to 360 degrees (0 = North, 90 = East, 180 = South, 270 = West)
- Elevation: -90 to +90 degrees (0 = horizon, 90 = zenith)

**Examples:**
```bash
# Point due East, 45 degrees above horizon
./point_mount.py goto 90 45

# Point South, 30 degrees above horizon
./point_mount.py goto 180 30

# Point to zenith (straight up)
./point_mount.py goto 0 90
```

The command will:
1. Display the current and target positions
2. Convert Az/El to RA/DEC coordinates
3. Slew the mount (showing real-time position updates)
4. Report the final achieved position

## Command Reference

| Command | Description |
|---------|-------------|
| `./point_mount.py` | Show current position |
| `./point_mount.py goto AZ EL` | Slew to Azimuth/Elevation coordinates |
| `./point_mount.py goto-eq RA DEC` | Slew to RA (hours) / DEC (degrees) |
| `./point_mount.py sync AZ EL` | Calibrate: tell mount it is pointing at Az/El |
| `./point_mount.py sync-eq RA DEC` | Calibrate: tell mount it is pointing at RA/DEC |
| `./point_mount.py set-location LAT LON` | Set observer geographic location |
| `./point_mount.py status` | Show detailed mount status |
| `./point_mount.py track` | Live position display (Ctrl+C to stop) |
| `./point_mount.py stop` | Emergency stop all motion |

## Quick Start Checklist

1. [ ] Install software: `./install_dependencies.sh`
2. [ ] Connect and power on the mount
3. [ ] Level the tripod
4. [ ] Polar align the mount (point RA axis at Polaris)
5. [ ] Start INDI server: `./start_server.sh`
6. [ ] Set location: `./point_mount.py set-location LAT LON`
7. [ ] Calibrate: Point at known star, run `./point_mount.py sync-eq RA DEC`
8. [ ] Command: `./point_mount.py goto AZ EL`

## File Descriptions

| File | Purpose |
|------|---------|
| `point_mount.py` | Main mount control script |
| `start_server.sh` | Starts the INDI server |
| `install_dependencies.sh` | Installs required software |
| `diagnose.py` | Diagnostic tool for troubleshooting |
| `.mount_config.json` | Stores your location setting (auto-created) |

## Troubleshooting

### "INDI server not running"

Start the server in a separate terminal:
```bash
./start_server.sh
```

### "Location not set"

Set your geographic location:
```bash
./point_mount.py set-location <LAT> <LON>
```

### "Cannot read position"

1. Check that the INDI server is running
2. Wait a few seconds for the mount to connect
3. Run `python3 diagnose.py` to check the connection

### Mount points to wrong location

The mount needs calibration. Sync to a known reference:
```bash
# Point at a known star and sync
./point_mount.py sync-eq <RA> <DEC>
```

### Mount does not move

1. Check that the mount is powered on (12V)
2. Verify USB connection with `python3 diagnose.py`
3. Restart the INDI server: stop it with Ctrl+C, then run `./start_server.sh` again
4. Check for obstructions or mechanical limits

### "No USB serial devices found"

1. Verify the mount is powered on
2. Check the USB cable connection
3. Try a different USB port
4. Check `dmesg | tail -20` for USB connection errors

### Permission denied on serial port

Add your user to the dialout group and log out/in:
```bash
sudo usermod -a -G dialout $USER
```
Then log out and log back in.

## Technical Details

### Communication Protocol

The system uses INDI (Instrument Neutral Distributed Interface) to communicate with the mount. The `indi_staradventurergti_telescope` driver handles the low-level serial communication.

### Coordinate Conversion

When you specify Az/El coordinates, the script:
1. Gets the current Local Sidereal Time (LST) from the INDI driver
2. Converts Az/El to Hour Angle and Declination using spherical trigonometry
3. Calculates Right Ascension from LST and Hour Angle
4. Sends RA/DEC coordinates to the mount's GoTo system

### Motor Specifications

- RA axis: 3,628,800 steps per 360 degrees
- DEC axis: 2,903,040 steps per 360 degrees
- Both axes slew at approximately 800x sidereal rate during GoTo

## Stopping the System

1. Stop any running GoTo: `./point_mount.py stop`
2. Stop the INDI server: Press Ctrl+C in the server terminal
3. Power off the mount
