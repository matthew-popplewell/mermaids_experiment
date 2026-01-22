#!/usr/bin/env python3.10
"""
Star Adventurer GTi Mount Control

Controls the mount using INDI GoTo functionality for Az/El positioning.
Both RA and DEC motors are controlled via the GoTo interface.

Usage:
    ./point_mount.py                      # Show current position
    ./point_mount.py goto AZ EL           # Slew to Az/El coordinates
    ./point_mount.py goto-eq RA DEC       # Slew to RA/DEC (hours, degrees)
    ./point_mount.py sync AZ EL           # Calibrate: "I am pointing at Az/El"
    ./point_mount.py sync-eq RA DEC       # Calibrate: "I am pointing at RA/DEC"
    ./point_mount.py set-location LAT LON # Set geographic location
    ./point_mount.py gps-location         # Get location from GPS receiver
    ./point_mount.py gps-location --port /dev/ttyUSB0  # Specify GPS port
    ./point_mount.py stop                 # Emergency stop all motion
    ./point_mount.py track                # Live position tracking display
    ./point_mount.py status               # Show detailed mount status

Calibration Example:
    # Point mount at Polaris, then sync to its coordinates
    ./point_mount.py sync-eq 2.53 89.26

    # Or sync using a known Az/El (e.g., pointing due North at horizon)
    ./point_mount.py sync 0 0

GoTo Example:
    ./point_mount.py set-location 39.917494,-105.0039301   # Set to Advanced Space HQ
    ./point_mount.py goto 90 45                    # Point to Az=90, El=45
"""
import sys
import time
import json
import os
import subprocess
import math

CONFIG_FILE = os.path.join(os.path.dirname(__file__), '.mount_config.json')

DEVICE = 'Star Adventurer GTi'
STEPS_PER_360_RA = 3628800.0   # Axis 1 (RA)
STEPS_PER_360_DEC = 2903040.0  # Axis 2 (Dec)

TOLERANCE_DEG = 0.5
GOTO_TIMEOUT = 120  # 5 minutes max for GoTo


def indi_get(prop):
    """Get INDI property value."""
    try:
        r = subprocess.run(['indi_getprop', f'{DEVICE}.{prop}'],
                          capture_output=True, text=True, timeout=5)
        if '=' in r.stdout:
            return r.stdout.strip().split('=')[1]
    except:
        pass
    return None


def indi_set(prop, value=None):
    """Set INDI property value(s).

    Can be called as:
        indi_set('PROP.ELEMENT', 'value')     - Single property
        indi_set('PROP.A=1;B=2')              - Multiple properties
    """
    if value is not None:
        cmd = f'{DEVICE}.{prop}={value}'
    else:
        # Assume prop contains the full property=value string(s)
        cmd = f'{DEVICE}.{prop}'
    subprocess.run(['indi_setprop', cmd], capture_output=True, timeout=5)


def stop_all():
    """Stop all motion immediately using abort."""
    indi_set('TELESCOPE_ABORT_MOTION.ABORT', 'On')


def get_steps():
    """Get current step positions."""
    ra = indi_get('CURRENTSTEPPERS.RAStepsCurrent')
    dec = indi_get('CURRENTSTEPPERS.DEStepsCurrent')
    if ra and dec:
        return float(ra), float(dec)
    return None, None


def get_horizontal():
    """Get current Az/Alt position."""
    az = indi_get('HORIZONTAL_COORD.AZ')
    alt = indi_get('HORIZONTAL_COORD.ALT')
    if az and alt:
        return float(az), float(alt)
    return None, None


def get_equatorial():
    """Get current RA/DEC position."""
    ra = indi_get('EQUATORIAL_EOD_COORD.RA')
    dec = indi_get('EQUATORIAL_EOD_COORD.DEC')
    if ra and dec:
        return float(ra), float(dec)
    return None, None


def load_config():
    """Load configuration (geographic location)."""
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
    """Set geographic coordinates. Required for Az/Alt GoTo."""
    config = load_config()

    if lat is not None and lon is not None:
        config['lat'] = lat
        config['lon'] = lon
        save_config(config)

    lat = config.get('lat')
    lon = config.get('lon')

    if lat is None or lon is None:
        return False

    indi_set(f'GEOGRAPHIC_COORD.LAT={lat};LONG={lon}')
    return True


def get_lst():
    """Get local sidereal time from INDI (in hours)."""
    lst = indi_get('TIME_LST.LST')
    if lst:
        return float(lst)
    return None


def azalt_to_radec(az, alt, lat):
    """Convert Az/Alt to RA/DEC using current LST.

    Args:
        az: Azimuth in degrees (0=North, 90=East)
        alt: Altitude in degrees
        lat: Observer latitude in degrees

    Returns:
        (ra_hours, dec_degrees) or None if conversion fails
    """
    lst = get_lst()
    if lst is None:
        return None

    # Convert to radians
    az_rad = math.radians(az)
    alt_rad = math.radians(alt)
    lat_rad = math.radians(lat)

    # Calculate declination
    sin_dec = math.sin(alt_rad) * math.sin(lat_rad) + \
              math.cos(alt_rad) * math.cos(lat_rad) * math.cos(az_rad)
    dec_rad = math.asin(max(-1, min(1, sin_dec)))

    # Calculate hour angle
    cos_dec = math.cos(dec_rad)
    if abs(cos_dec) < 1e-10:
        # At celestial pole, HA is undefined
        ha_rad = 0
    else:
        sin_ha = -math.sin(az_rad) * math.cos(alt_rad) / cos_dec
        cos_ha = (math.sin(alt_rad) - math.sin(dec_rad) * math.sin(lat_rad)) / \
                 (cos_dec * math.cos(lat_rad))
        ha_rad = math.atan2(sin_ha, cos_ha)

    # Calculate RA = LST - HA
    ha_hours = math.degrees(ha_rad) / 15.0
    ra_hours = lst - ha_hours

    # Normalize RA to 0-24 hours
    while ra_hours < 0:
        ra_hours += 24
    while ra_hours >= 24:
        ra_hours -= 24

    dec_deg = math.degrees(dec_rad)

    return ra_hours, dec_deg


def wait_for_goto(timeout=GOTO_TIMEOUT, show_progress=True):
    """Wait for GoTo to complete by monitoring step changes."""
    start = time.time()
    last_ra_steps = None
    last_dec_steps = None
    stable_count = 0
    moving_detected = False

    while time.time() - start < timeout:
        ra_steps, dec_steps = get_steps()
        az, alt = get_horizontal()
        ra, dec = get_equatorial()

        if show_progress and az is not None:
            elapsed = time.time() - start
            print(f'\r  [{elapsed:4.0f}s] Az={az:6.1f}°  Alt={alt:+6.1f}°  RA={ra:.2f}h  DEC={dec:+.1f}°  ',
                  end='', flush=True)

        if last_ra_steps is not None:
            # Check if position is changing
            ra_delta = abs(ra_steps - last_ra_steps)
            dec_delta = abs(dec_steps - last_dec_steps)

            if ra_delta > 100 or dec_delta > 100:
                # Mount is moving
                moving_detected = True
                stable_count = 0
            else:
                # Position stable
                stable_count += 1
                # Wait for position to be stable for 2 seconds after movement detected
                if moving_detected and stable_count >= 4:
                    if show_progress:
                        print(' Done!')
                    return True
                # If never detected movement, wait a bit longer before giving up
                elif not moving_detected and stable_count >= 6:
                    if show_progress:
                        print(' No movement detected')
                    return False

        last_ra_steps = ra_steps
        last_dec_steps = dec_steps
        time.sleep(0.5)

    if show_progress:
        print(' Timeout!')
    return False


def goto_horizontal(target_az, target_alt):
    """Slew to target Az/Alt position by converting to RA/DEC."""
    # Get config for latitude
    config = load_config()
    lat = config.get('lat')
    if lat is None:
        print('ERROR: Location not set.')
        print('  Run: ./point_mount.py set-location LAT LON')
        return False

    # Check current position
    current_az, current_alt = get_horizontal()
    if current_az is None:
        print('ERROR: Cannot read position')
        return False

    print(f'Current: Az={current_az:.1f}°  Alt={current_alt:+.1f}°')
    print(f'Target:  Az={target_az:.1f}°  Alt={target_alt:+.1f}°')

    # Safety check - don't point below horizon
    if target_alt < -5:
        print(f'ERROR: Target altitude {target_alt:.1f}° is below horizon')
        return False

    # Convert Az/Alt to RA/DEC
    result = azalt_to_radec(target_az, target_alt, lat)
    if result is None:
        print('ERROR: Cannot convert coordinates (LST unavailable)')
        return False

    target_ra, target_dec = result
    print(f'(Converted to RA={target_ra:.2f}h  DEC={target_dec:+.1f}°)')

    # Set to SLEW mode and send coordinates
    indi_set('ON_COORD_SET.SLEW', 'On')
    time.sleep(0.1)

    print('Slewing...', flush=True)
    indi_set(f'EQUATORIAL_EOD_COORD.RA={target_ra};DEC={target_dec}')

    time.sleep(0.5)  # Give it time to start

    if wait_for_goto():
        final_az, final_alt = get_horizontal()
        print(f'Reached: Az={final_az:.1f}°  Alt={final_alt:+.1f}°')
        return True
    else:
        stop_all()
        return False


def goto_equatorial(target_ra, target_dec):
    """Slew to target RA/DEC position using GoTo."""
    current_ra, current_dec = get_equatorial()
    if current_ra is None:
        print('ERROR: Cannot read position')
        return False

    print(f'Current: RA={current_ra:.3f}h  DEC={current_dec:+.2f}°')
    print(f'Target:  RA={target_ra:.3f}h  DEC={target_dec:+.2f}°')

    # Set to SLEW mode and send coordinates
    indi_set('ON_COORD_SET.SLEW', 'On')
    time.sleep(0.1)

    print('Slewing...', flush=True)
    indi_set(f'EQUATORIAL_EOD_COORD.RA={target_ra};DEC={target_dec}')

    time.sleep(0.5)

    if wait_for_goto():
        final_ra, final_dec = get_equatorial()
        print(f'Reached: RA={final_ra:.3f}h  DEC={final_dec:+.2f}°')
        return True
    else:
        stop_all()
        return False


def sync_equatorial(sync_ra, sync_dec):
    """Sync mount to known RA/DEC coordinates (calibration)."""
    current_ra, current_dec = get_equatorial()
    if current_ra is None:
        print('ERROR: Cannot read position')
        return False

    print(f'Before sync: RA={current_ra:.3f}h  DEC={current_dec:+.2f}°')
    print(f'Syncing to:  RA={sync_ra:.3f}h  DEC={sync_dec:+.2f}°')

    # Set to SYNC mode and send coordinates
    indi_set('ON_COORD_SET.SYNC', 'On')
    time.sleep(0.1)

    indi_set(f'EQUATORIAL_EOD_COORD.RA={sync_ra};DEC={sync_dec}')
    time.sleep(0.5)

    # Verify sync took effect
    new_ra, new_dec = get_equatorial()
    print(f'After sync:  RA={new_ra:.3f}h  DEC={new_dec:+.2f}°')

    # Switch back to SLEW mode for future commands
    indi_set('ON_COORD_SET.SLEW', 'On')

    return True


def sync_horizontal(sync_az, sync_alt):
    """Sync mount to known Az/Alt coordinates (calibration)."""
    config = load_config()
    lat = config.get('lat')
    if lat is None:
        print('ERROR: Location not set.')
        print('  Run: ./point_mount.py set-location LAT LON')
        return False

    current_az, current_alt = get_horizontal()
    if current_az is None:
        print('ERROR: Cannot read position')
        return False

    print(f'Before sync: Az={current_az:.1f}°  Alt={current_alt:+.1f}°')
    print(f'Syncing to:  Az={sync_az:.1f}°  Alt={sync_alt:+.1f}°')

    # Convert Az/Alt to RA/DEC
    result = azalt_to_radec(sync_az, sync_alt, lat)
    if result is None:
        print('ERROR: Cannot convert coordinates')
        return False

    sync_ra, sync_dec = result
    print(f'(Equivalent: RA={sync_ra:.2f}h  DEC={sync_dec:+.1f}°)')

    # Set to SYNC mode and send coordinates
    indi_set('ON_COORD_SET.SYNC', 'On')
    time.sleep(0.1)

    indi_set(f'EQUATORIAL_EOD_COORD.RA={sync_ra};DEC={sync_dec}')
    time.sleep(0.5)

    # Verify sync took effect
    new_az, new_alt = get_horizontal()
    print(f'After sync:  Az={new_az:.1f}°  Alt={new_alt:+.1f}°')

    # Switch back to SLEW mode for future commands
    indi_set('ON_COORD_SET.SLEW', 'On')

    return True


def show_status():
    """Show detailed mount status."""
    print('=== Mount Status ===\n')

    # Connection
    conn = indi_get('CONNECTION.CONNECT')
    print(f'Connected: {conn}')

    # Location
    lat = indi_get('GEOGRAPHIC_COORD.LAT')
    lon = indi_get('GEOGRAPHIC_COORD.LONG')
    if lat and float(lat) > 1e-10:
        print(f'Location: Lat={float(lat):.4f}° Lon={float(lon):.4f}°')
    else:
        print('Location: NOT SET (required for Az/Alt GoTo)')

    # Position
    az, alt = get_horizontal()
    if az:
        print(f'\nHorizontal: Az={az:.2f}°  Alt={alt:+.2f}°')

    ra, dec = get_equatorial()
    if ra:
        print(f'Equatorial: RA={ra:.4f}h  DEC={dec:+.2f}°')

    ra_steps, dec_steps = get_steps()
    if ra_steps:
        print(f'Steps: RA={ra_steps:.0f}  DEC={dec_steps:.0f}')

    # Status
    print(f'\nRA GoTo: {indi_get("RASTATUS.RAGoto")}')
    print(f'DEC GoTo: {indi_get("DESTATUS.DEGoto")}')

    # Mode
    coord_mode = 'SLEW' if indi_get('ON_COORD_SET.SLEW') == 'On' else \
                 'TRACK' if indi_get('ON_COORD_SET.TRACK') == 'On' else 'SYNC'
    print(f'Coord mode: {coord_mode}')


def main():
    args = sys.argv[1:]

    if indi_get('CONNECTION.CONNECT') is None:
        print('ERROR: INDI server not running. Start with ./start_server.sh')
        return 1

    # Load and apply saved location
    setup_location()

    if len(args) == 0:
        # Show current position
        az, alt = get_horizontal()
        ra, dec = get_equatorial()

        if az is not None and abs(az) > 0.001:
            print(f'Position: Az={az:.1f}°  Alt={alt:+.1f}°')
            print(f'          RA={ra:.3f}h  DEC={dec:+.1f}°')
        elif ra is not None:
            print(f'Position: RA={ra:.3f}h  DEC={dec:+.1f}°')
            config = load_config()
            if 'lat' not in config:
                print('  (Set location for Az/Alt: ./point_mount.py set-location LAT LON)')
        else:
            print('ERROR: Cannot read position')
        return 0

    elif args[0] == 'stop':
        stop_all()
        print('All motion stopped.')
        return 0

    elif args[0] == 'status':
        show_status()
        return 0

    elif args[0] == 'set-location' and len(args) == 3:
        try:
            lat = float(args[1])
            lon = float(args[2])
        except ValueError:
            print('ERROR: LAT and LON must be numbers')
            return 1
        if abs(lat) > 90:
            print('ERROR: Latitude must be between -90 and 90')
            return 1
        if abs(lon) > 180:
            print('ERROR: Longitude must be between -180 and 180')
            return 1
        setup_location(lat, lon)
        print(f'Location set: Lat={lat}° Lon={lon}°')
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

            # Save location
            setup_location(location['lat'], location['lon'])
            print('Location saved to config.')
            return 0

        except GPSNotAvailable as e:
            print(f'\n\nERROR: {e}')
            print('\nTroubleshooting:')
            print('  1. Connect USB GPS receiver')
            print('  2. Check device: ls /dev/ttyUSB* /dev/ttyACM*')
            print('  3. Check permissions: sudo usermod -a -G dialout $USER')
            print('  4. Specify port manually: ./point_mount.py gps-location --port /dev/ttyUSB0')
            return 1

        except FixTimeoutError as e:
            print(f'\n\nERROR: {e}')
            print('\nGPS has no satellite fix. Try:')
            print('  - Move to a location with clear sky view')
            print('  - Wait longer: ./point_mount.py gps-location --wait 120')
            return 1

    elif args[0] == 'goto' and len(args) == 3:
        try:
            target_az = float(args[1])
            target_alt = float(args[2])
        except ValueError:
            print('ERROR: AZ and ALT must be numbers')
            return 1
        return 0 if goto_horizontal(target_az, target_alt) else 1

    elif args[0] == 'goto-eq' and len(args) == 3:
        try:
            target_ra = float(args[1])
            target_dec = float(args[2])
        except ValueError:
            print('ERROR: RA and DEC must be numbers')
            return 1
        return 0 if goto_equatorial(target_ra, target_dec) else 1

    elif args[0] == 'sync' and len(args) == 3:
        try:
            sync_az = float(args[1])
            sync_alt = float(args[2])
        except ValueError:
            print('ERROR: AZ and ALT must be numbers')
            return 1
        return 0 if sync_horizontal(sync_az, sync_alt) else 1

    elif args[0] == 'sync-eq' and len(args) == 3:
        try:
            sync_ra = float(args[1])
            sync_dec = float(args[2])
        except ValueError:
            print('ERROR: RA and DEC must be numbers')
            return 1
        return 0 if sync_equatorial(sync_ra, sync_dec) else 1

    elif args[0] == 'track':
        print('Live position tracking. Press Ctrl+C to stop.\n')

        try:
            while True:
                az, alt = get_horizontal()
                ra, dec = get_equatorial()
                ra_steps, dec_steps = get_steps()

                if az is not None:
                    print(f'\rAz={az:7.2f}°  Alt={alt:+7.2f}°  |  '
                          f'RA={ra:7.3f}h  DEC={dec:+7.2f}°  |  '
                          f'Steps: {ra_steps:.0f}/{dec_steps:.0f}    ',
                          end='', flush=True)
                time.sleep(0.5)
        except KeyboardInterrupt:
            print('\n\nStopped.')
        return 0

    else:
        print(__doc__)
        return 1


if __name__ == '__main__':
    sys.exit(main())
