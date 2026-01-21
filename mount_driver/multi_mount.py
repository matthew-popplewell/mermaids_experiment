#!/usr/bin/env python3.10
"""
Multi-Mount Control for Star Adventurer GTi

Controls multiple co-located mounts to point at the same Az/El coordinates.
All mounts share the same geographic location.

Usage:
    ./multi_mount.py status                 # Show status of all mounts
    ./multi_mount.py connect                # Auto-connect all mounts to ports
    ./multi_mount.py goto AZ EL             # Slew ALL mounts to Az/El
    ./multi_mount.py goto AZ EL --mount 1   # Slew only Mount 1
    ./multi_mount.py sync AZ EL             # Sync ALL mounts to Az/El
    ./multi_mount.py sync AZ EL --mount 2   # Sync only Mount 2
    ./multi_mount.py set-location LAT LON   # Set location (shared by all)
    ./multi_mount.py gps-location           # Get location from GPS receiver
    ./multi_mount.py assign                 # Interactive mount assignment
    ./multi_mount.py stop                   # Emergency stop ALL mounts

Example:
    ./start_server.sh                       # Start INDI server (auto-detects mounts)
    ./multi_mount.py connect                # Connect all mounts to ports
    ./multi_mount.py set-location 36.17 -115.14
    ./multi_mount.py sync 0 45
    ./multi_mount.py goto 90 45             # All mounts point to Az=90, El=45
"""
import sys
import time
import json
import os
import subprocess
import math
from concurrent.futures import ThreadPoolExecutor, as_completed

CONFIG_FILE = os.path.join(os.path.dirname(__file__), '.multi_mount_config.json')

# Mount naming convention used by INDI
MOUNT_PREFIX = 'Mount '

STEPS_PER_360_RA = 3628800.0
STEPS_PER_360_DEC = 2903040.0
GOTO_TIMEOUT = 300


def indi_get(device, prop):
    """Get INDI property value for a specific device."""
    try:
        r = subprocess.run(['indi_getprop', f'{device}.{prop}'],
                          capture_output=True, text=True, timeout=5)
        if '=' in r.stdout:
            return r.stdout.strip().split('=')[1]
    except:
        pass
    return None


def indi_set(device, prop, value=None):
    """Set INDI property value for a specific device."""
    if value is not None:
        cmd = f'{device}.{prop}={value}'
    else:
        cmd = f'{device}.{prop}'
    subprocess.run(['indi_setprop', cmd], capture_output=True, timeout=5)


def discover_mounts():
    """Discover all connected mounts via INDI."""
    mounts = []

    # Try mount numbers 1-10
    for i in range(1, 11):
        device = f'{MOUNT_PREFIX}{i}'
        conn = indi_get(device, 'CONNECTION.CONNECT')
        if conn is not None:
            mounts.append({
                'id': i,
                'device': device,
                'connected': conn == 'On'
            })

    return mounts


def get_mount_status(mount):
    """Get detailed status for a single mount."""
    device = mount['device']

    # Get port
    port = indi_get(device, 'DEVICE_PORT.PORT')

    # Get position
    az = indi_get(device, 'HORIZONTAL_COORD.AZ')
    alt = indi_get(device, 'HORIZONTAL_COORD.ALT')
    ra = indi_get(device, 'EQUATORIAL_EOD_COORD.RA')
    dec = indi_get(device, 'EQUATORIAL_EOD_COORD.DEC')

    return {
        'id': mount['id'],
        'device': device,
        'connected': mount['connected'],
        'port': port,
        'az': float(az) if az else None,
        'alt': float(alt) if alt else None,
        'ra': float(ra) if ra else None,
        'dec': float(dec) if dec else None
    }


def load_config():
    """Load configuration."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}


def save_config(config):
    """Save configuration."""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


def setup_location(lat=None, lon=None):
    """Set geographic coordinates for all mounts."""
    config = load_config()

    if lat is not None and lon is not None:
        config['lat'] = lat
        config['lon'] = lon
        save_config(config)

    lat = config.get('lat')
    lon = config.get('lon')

    if lat is None or lon is None:
        return False

    # Apply to all discovered mounts
    mounts = discover_mounts()
    for mount in mounts:
        indi_set(mount['device'], f'GEOGRAPHIC_COORD.LAT={lat};LONG={lon}')

    return True


def get_lst(device):
    """Get local sidereal time from a mount."""
    lst = indi_get(device, 'TIME_LST.LST')
    if lst:
        return float(lst)
    return None


def azalt_to_radec(az, alt, lat, device):
    """Convert Az/Alt to RA/DEC using LST from specified mount."""
    lst = get_lst(device)
    if lst is None:
        return None

    az_rad = math.radians(az)
    alt_rad = math.radians(alt)
    lat_rad = math.radians(lat)

    sin_dec = math.sin(alt_rad) * math.sin(lat_rad) + \
              math.cos(alt_rad) * math.cos(lat_rad) * math.cos(az_rad)
    dec_rad = math.asin(max(-1, min(1, sin_dec)))

    cos_dec = math.cos(dec_rad)
    if abs(cos_dec) < 1e-10:
        ha_rad = 0
    else:
        sin_ha = -math.sin(az_rad) * math.cos(alt_rad) / cos_dec
        cos_ha = (math.sin(alt_rad) - math.sin(dec_rad) * math.sin(lat_rad)) / \
                 (cos_dec * math.cos(lat_rad))
        ha_rad = math.atan2(sin_ha, cos_ha)

    ha_hours = math.degrees(ha_rad) / 15.0
    ra_hours = lst - ha_hours

    while ra_hours < 0:
        ra_hours += 24
    while ra_hours >= 24:
        ra_hours -= 24

    return ra_hours, math.degrees(dec_rad)


def wait_for_mount_goto(device, timeout=GOTO_TIMEOUT):
    """Wait for a single mount's GoTo to complete."""
    start = time.time()
    last_ra_steps = None
    last_dec_steps = None
    stable_count = 0
    moving_detected = False

    while time.time() - start < timeout:
        ra_steps = indi_get(device, 'CURRENTSTEPPERS.RAStepsCurrent')
        dec_steps = indi_get(device, 'CURRENTSTEPPERS.DEStepsCurrent')

        if ra_steps and dec_steps:
            ra_steps = float(ra_steps)
            dec_steps = float(dec_steps)

            if last_ra_steps is not None:
                ra_delta = abs(ra_steps - last_ra_steps)
                dec_delta = abs(dec_steps - last_dec_steps)

                if ra_delta > 100 or dec_delta > 100:
                    moving_detected = True
                    stable_count = 0
                else:
                    stable_count += 1
                    if moving_detected and stable_count >= 4:
                        return True
                    elif not moving_detected and stable_count >= 6:
                        return False

            last_ra_steps = ra_steps
            last_dec_steps = dec_steps

        time.sleep(0.5)

    return False


def goto_mount(device, target_ra, target_dec):
    """Send GoTo command to a single mount."""
    indi_set(device, 'ON_COORD_SET.SLEW', 'On')
    time.sleep(0.1)
    indi_set(device, f'EQUATORIAL_EOD_COORD.RA={target_ra};DEC={target_dec}')
    return wait_for_mount_goto(device)


def sync_mount(device, sync_ra, sync_dec):
    """Sync a single mount to coordinates."""
    indi_set(device, 'ON_COORD_SET.SYNC', 'On')
    time.sleep(0.1)
    indi_set(device, f'EQUATORIAL_EOD_COORD.RA={sync_ra};DEC={sync_dec}')
    time.sleep(0.5)
    indi_set(device, 'ON_COORD_SET.SLEW', 'On')
    return True


def stop_mount(device):
    """Stop a single mount."""
    indi_set(device, 'TELESCOPE_ABORT_MOTION.ABORT', 'On')


def goto_all_mounts(target_az, target_alt, mount_filter=None):
    """Command all mounts (or specific mount) to Az/El coordinates."""
    config = load_config()
    lat = config.get('lat')
    if lat is None:
        print('ERROR: Location not set. Run: ./multi_mount.py set-location LAT LON')
        return False

    mounts = discover_mounts()
    if not mounts:
        print('ERROR: No mounts discovered. Is INDI server running?')
        return False

    # Filter to specific mount if requested
    if mount_filter is not None:
        mounts = [m for m in mounts if m['id'] == mount_filter]
        if not mounts:
            print(f'ERROR: Mount {mount_filter} not found')
            return False

    # Get first connected mount for coordinate conversion
    first_device = mounts[0]['device']
    result = azalt_to_radec(target_az, target_alt, lat, first_device)
    if result is None:
        print('ERROR: Cannot convert coordinates')
        return False

    target_ra, target_dec = result

    print(f'Target: Az={target_az:.1f}  Alt={target_alt:+.1f}')
    print(f'        RA={target_ra:.2f}h  DEC={target_dec:+.1f}')
    print()

    # Start GoTo on all mounts in parallel
    print(f'Slewing {len(mounts)} mount(s)...')

    results = {}
    with ThreadPoolExecutor(max_workers=len(mounts)) as executor:
        futures = {
            executor.submit(goto_mount, m['device'], target_ra, target_dec): m
            for m in mounts
        }

        for future in as_completed(futures):
            mount = futures[future]
            try:
                success = future.result()
                results[mount['id']] = success
                status = 'Done' if success else 'FAILED'

                # Get final position
                az = indi_get(mount['device'], 'HORIZONTAL_COORD.AZ')
                alt = indi_get(mount['device'], 'HORIZONTAL_COORD.ALT')
                if az and alt:
                    print(f'  Mount {mount["id"]}: {status} - Az={float(az):.1f}  Alt={float(alt):+.1f}')
                else:
                    print(f'  Mount {mount["id"]}: {status}')
            except Exception as e:
                results[mount['id']] = False
                print(f'  Mount {mount["id"]}: ERROR - {e}')

    return all(results.values())


def sync_all_mounts(sync_az, sync_alt, mount_filter=None):
    """Sync all mounts (or specific mount) to Az/El coordinates."""
    config = load_config()
    lat = config.get('lat')
    if lat is None:
        print('ERROR: Location not set. Run: ./multi_mount.py set-location LAT LON')
        return False

    mounts = discover_mounts()
    if not mounts:
        print('ERROR: No mounts discovered')
        return False

    if mount_filter is not None:
        mounts = [m for m in mounts if m['id'] == mount_filter]
        if not mounts:
            print(f'ERROR: Mount {mount_filter} not found')
            return False

    print(f'Syncing {len(mounts)} mount(s) to Az={sync_az:.1f}  Alt={sync_alt:+.1f}')

    for mount in mounts:
        device = mount['device']
        result = azalt_to_radec(sync_az, sync_alt, lat, device)
        if result is None:
            print(f'  Mount {mount["id"]}: ERROR - Cannot convert coordinates')
            continue

        sync_ra, sync_dec = result
        sync_mount(device, sync_ra, sync_dec)

        # Verify
        az = indi_get(device, 'HORIZONTAL_COORD.AZ')
        alt = indi_get(device, 'HORIZONTAL_COORD.ALT')
        if az and alt:
            print(f'  Mount {mount["id"]}: Synced - Now reads Az={float(az):.1f}  Alt={float(alt):+.1f}')
        else:
            print(f'  Mount {mount["id"]}: Synced')

    return True


def stop_all_mounts():
    """Emergency stop all mounts."""
    mounts = discover_mounts()
    for mount in mounts:
        stop_mount(mount['device'])
    print(f'Stopped {len(mounts)} mount(s)')


def show_status():
    """Show status of all mounts."""
    mounts = discover_mounts()

    if not mounts:
        print('No mounts discovered. Is INDI server running?')
        print('  Start with: ./start_server.sh')
        return

    config = load_config()
    lat = config.get('lat')
    lon = config.get('lon')

    print('=== Multi-Mount Status ===\n')

    if lat:
        print(f'Location: Lat={lat:.4f}  Lon={lon:.4f}')
    else:
        print('Location: NOT SET')

    print(f'\nMounts discovered: {len(mounts)}\n')

    for mount in mounts:
        status = get_mount_status(mount)
        conn_str = 'CONNECTED' if status['connected'] else 'disconnected'

        print(f'Mount {status["id"]}: {conn_str}')
        if status['port']:
            print(f'  Port: {status["port"]}')
        if status['az'] is not None:
            print(f'  Position: Az={status["az"]:.1f}  Alt={status["alt"]:+.1f}')
            print(f'            RA={status["ra"]:.3f}h  DEC={status["dec"]:+.1f}')
        print()


def get_available_ports():
    """Get list of available ttyACM ports (Star Adventurer GTi mounts)."""
    ports = []
    for i in range(10):
        port = f'/dev/ttyACM{i}'
        if os.path.exists(port):
            ports.append(port)
    return ports


def auto_connect():
    """Automatically assign ports and connect all mounts."""
    mounts = discover_mounts()

    if not mounts:
        print('No mounts discovered. Is INDI server running?')
        return False

    ports = get_available_ports()
    if not ports:
        print('No USB devices found at /dev/ttyACM*')
        return False

    if len(ports) < len(mounts):
        print(f'Warning: Found {len(ports)} ports but {len(mounts)} mount instances')

    print(f'Auto-connecting {len(mounts)} mount(s) to {len(ports)} port(s)...')

    # Assign each mount to a port and connect
    for i, mount in enumerate(mounts):
        if i >= len(ports):
            print(f'  Mount {mount["id"]}: No available port')
            continue

        device = mount['device']
        port = ports[i]

        # Set port
        indi_set(device, 'DEVICE_PORT.PORT', port)
        time.sleep(0.3)

        # Connect
        indi_set(device, 'CONNECTION.CONNECT', 'On')
        time.sleep(2)

        # Verify connection
        conn = indi_get(device, 'CONNECTION.CONNECT')
        if conn == 'On':
            print(f'  Mount {mount["id"]}: Connected on {port}')
        else:
            print(f'  Mount {mount["id"]}: FAILED to connect on {port}')

    # Apply location to all connected mounts
    setup_location()

    return True


def assign_ports():
    """Interactive port assignment for mounts."""
    mounts = discover_mounts()

    if not mounts:
        print('No mounts discovered. Start INDI server first.')
        return

    ports = get_available_ports()
    if not ports:
        print('No USB devices found at /dev/ttyACM*')
        return

    print('Available ports:', ports)
    print()
    print('Assign ports to mounts:')

    for mount in mounts:
        device = mount['device']
        current_port = indi_get(device, 'DEVICE_PORT.PORT')
        print(f'\nMount {mount["id"]} (current: {current_port})')

        for i, port in enumerate(ports):
            print(f'  {i+1}. {port}')

        choice = input(f'Select port for Mount {mount["id"]} [1-{len(ports)}] or Enter to skip: ').strip()

        if choice and choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(ports):
                new_port = ports[idx]
                indi_set(device, 'DEVICE_PORT.PORT', new_port)
                print(f'  Set to {new_port}')

                # Reconnect
                indi_set(device, 'CONNECTION.DISCONNECT', 'On')
                time.sleep(1)
                indi_set(device, 'CONNECTION.CONNECT', 'On')
                time.sleep(2)


def main():
    args = sys.argv[1:]

    # Check for --mount N flag
    mount_filter = None
    if '--mount' in args:
        idx = args.index('--mount')
        if idx + 1 < len(args):
            try:
                mount_filter = int(args[idx + 1])
            except ValueError:
                print('ERROR: --mount requires a number')
                return 1
            args = args[:idx] + args[idx+2:]

    # Check INDI server
    result = subprocess.run(['indi_getprop'], capture_output=True, text=True, timeout=5)
    if result.returncode != 0 and 'unable to connect' in result.stderr.lower():
        print('ERROR: INDI server not running. Start with ./start_server.sh')
        return 1

    # Apply saved location to all mounts
    setup_location()

    if len(args) == 0:
        show_status()
        return 0

    elif args[0] == 'status':
        show_status()
        return 0

    elif args[0] == 'stop':
        stop_all_mounts()
        return 0

    elif args[0] == 'connect':
        return 0 if auto_connect() else 1

    elif args[0] == 'assign':
        assign_ports()
        return 0

    elif args[0] == 'set-location' and len(args) == 3:
        try:
            lat = float(args[1])
            lon = float(args[2])
        except ValueError:
            print('ERROR: LAT and LON must be numbers')
            return 1
        if abs(lat) > 90 or abs(lon) > 180:
            print('ERROR: Invalid coordinates')
            return 1
        setup_location(lat, lon)
        print(f'Location set: Lat={lat}  Lon={lon}')
        return 0

    elif args[0] == 'gps-location':
        # Parse optional --wait argument
        timeout = 30
        if '--wait' in args:
            idx = args.index('--wait')
            if idx + 1 < len(args):
                try:
                    timeout = int(args[idx + 1])
                except ValueError:
                    print('ERROR: --wait requires a number (seconds)')
                    return 1

        # Parse optional --port argument
        port = None
        if '--port' in args:
            idx = args.index('--port')
            if idx + 1 < len(args):
                port = args[idx + 1]

        # Import GPS module (direct serial connection)
        try:
            from gps_serial import (
                get_gps_location, gps_available, format_location,
                GPSNotAvailable, FixTimeoutError
            )
        except ImportError:
            print('ERROR: GPS libraries not installed.')
            print('  Run: pip install pyserial pynmea2')
            return 1

        print(f'Reading GPS location (timeout: {timeout}s)...')

        def progress(sats, status):
            print(f'\r  {status} ({sats} satellites)   ', end='', flush=True)

        try:
            location = get_gps_location(timeout=timeout, port=port, progress_callback=progress)
            print('\n')
            print(format_location(location))
            print()

            # Save location (applies to all mounts)
            setup_location(location['lat'], location['lon'])
            print('Location saved to config (applies to all mounts).')
            return 0

        except GPSNotAvailable as e:
            print(f'\n\nERROR: {e}')
            print('\nTroubleshooting:')
            print('  1. Connect USB GPS receiver')
            print('  2. Check device: ls /dev/ttyUSB* /dev/ttyACM*')
            print('  3. Check permissions: sudo usermod -a -G dialout $USER')
            print('  4. Specify port manually: ./multi_mount.py gps-location --port /dev/ttyUSB0')
            return 1

        except FixTimeoutError as e:
            print(f'\n\nERROR: {e}')
            print('\nGPS has no satellite fix. Try:')
            print('  - Move to a location with clear sky view')
            print('  - Wait longer: ./multi_mount.py gps-location --wait 120')
            return 1

    elif args[0] == 'goto' and len(args) >= 3:
        try:
            target_az = float(args[1])
            target_alt = float(args[2])
        except ValueError:
            print('ERROR: AZ and EL must be numbers')
            return 1
        return 0 if goto_all_mounts(target_az, target_alt, mount_filter) else 1

    elif args[0] == 'sync' and len(args) >= 3:
        try:
            sync_az = float(args[1])
            sync_alt = float(args[2])
        except ValueError:
            print('ERROR: AZ and EL must be numbers')
            return 1
        return 0 if sync_all_mounts(sync_az, sync_alt, mount_filter) else 1

    else:
        print(__doc__)
        return 1


if __name__ == '__main__':
    sys.exit(main())
