# Star Adventurer GTi Mount Control

Control one or multiple Sky-Watcher Star Adventurer GTi mounts via INDI on Linux.

```bash
./point_mount.py goto 90 45      # Single mount: point to Az=90, El=45
./multi_mount.py goto 90 45      # Multiple mounts: all point to Az=90, El=45
./calibrate.py                   # Auto-calibrate via plate solving
```

## Installation

### Online Installation (Recommended)
```bash
./install_dependencies.sh
```

### Offline Installation
For machines without internet access, use the two-step process:

1. **On an internet-connected machine** (same Ubuntu version and architecture):
   ```bash
   ./prepare_offline_packages.sh
   ```

2. **Copy the entire project** (including `offline_packages/`) to the offline machine

3. **On the offline machine**:
   ```bash
   ./install_dependencies.sh --offline
   ```

See [docs/OFFLINE_INSTALLATION.md](../docs/OFFLINE_INSTALLATION.md) for detailed instructions.

### After Installation
source .venv/bin/activate

## Hardware Setup

1. Connect 12V power and USB cable to each mount
2. Verify connections: `python3 diagnose.py`

### Physical Alignment

1. Level the tripod with a bubble level
2. Point RA axis toward Polaris (northern hemisphere). Polar align mount manually (refer to physical user guide or SynScan Pro app).
3. Set home position: counterweight bar pointing down

## udev Rules (Recommended for Multiple Mounts)

udev rules give each mount a consistent device name regardless of USB port.

### Find Serial Numbers

```bash
python3 diagnose.py
```

Look for the `Serial:` field for each mount, or query directly:
```bash
udevadm info --query=property --name=/dev/ttyACM0 | grep ID_SERIAL_SHORT
```

### Generate and Install Rules

1. Edit `generate_udev_rules.py` with your serial numbers:
```python
my_serials = {
   'mount1': '4E9841685300',
   'mount2': '4EA9413D5700',
   'mount3': '4E89414B5300',
   'mount4': '4EBC41595300'
}
```

2. Generate and install:
```bash
python3 generate_udev_rules.py
sudo cp 99-telescopes.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

## Usage

### Start the Server

```bash
./start_server.sh      # Auto-detects mounts and connects them
./start_server.sh 4    # Force 4 mount instances
```

Keep this terminal open. Single mount appears as "Star Adventurer GTi"; multiple mounts as "Mount 1", "Mount 2", etc.

### Double check connection
./multi_mount.py connect

### Set Location

```bash
./point_mount.py set-location 36.17 -115.14   # Manual
./multi_mount.py set-location 36.17 -115.14
./point_mount.py gps-location                # From USB GPS
./multi_mount.py gps-location
```

### Calibrate

**Option 1: Automatic (plate solving)**
```bash
./calibrate.py              # Single mount
./calibrate.py --all        # All mounts
./calibrate.py --verify     # Check accuracy without syncing
```

**Option 2: Manual sync**
```bash
./point_mount.py sync 0 45              # Single mount
./multi_mount.py sync 0 45              # All mounts (parallel)
./multi_mount.py sync 0 45 --mount 1    # Specific mount
```

### Command Mounts

```bash
./point_mount.py goto 90 45             # Single mount
./multi_mount.py goto 90 45             # All mounts (parallel)
./multi_mount.py goto 90 45 --mount 2   # Specific mount
./multi_mount.py stop                   # Emergency stop all
```

### Check Status

```bash
./point_mount.py status     # Single mount details
./multi_mount.py status     # All mounts overview
```

## Troubleshooting

### Mount not detected
```bash
python3 diagnose.py
```
Check: power on, USB connected, try different port.

### Permission denied
```bash
sudo usermod -a -G dialout $USER
```
Then log out and back in.

### Mount not connecting via INDI

The server auto-connects, but you can manually connect:
```bash
indi_setprop "Star Adventurer GTi.CONNECTION.CONNECT=On"  # Single
indi_setprop "Mount 1.CONNECTION.CONNECT=On"              # Multi
```

### GPS not working
```bash
ls /dev/ttyUSB* /dev/ttyACM*                              # Find port
./point_mount.py gps-location --port /dev/ttyUSB0         # Specify port
./point_mount.py gps-location --wait 120                  # Longer timeout
```

### Plate solving fails
- Ensure clear sky with visible stars
- Try: `./calibrate.py --exposure 2.0 --gain 200`
- Check tetra3 database exists (see `asi_driver/` README)

## Files

| File | Purpose |
|------|---------|
| `point_mount.py` | Single mount control |
| `multi_mount.py` | Multiple mount control |
| `calibrate.py` | Auto-calibration via plate solving |
| `start_server.sh` | Start INDI server |
| `diagnose.py` | Show USB devices and serial numbers |
| `generate_udev_rules.py` | Generate udev rules |
| `gps_serial.py` | GPS location reader |
