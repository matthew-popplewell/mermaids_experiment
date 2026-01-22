"""CLI for multi-mount control.

Usage:
    mount-multi status                 # Show status of all mounts
    mount-multi connect                # Auto-connect all mounts to ports
    mount-multi goto AZ EL             # Slew ALL mounts to Az/El
    mount-multi goto AZ EL --mount 1   # Slew only Mount 1
    mount-multi sync AZ EL             # Sync ALL mounts to Az/El
    mount-multi sync AZ EL --mount 2   # Sync only Mount 2
    mount-multi set-location LAT LON   # Set location (shared by all)
    mount-multi gps-location           # Get location from GPS receiver
    mount-multi stop                   # Emergency stop ALL mounts
    mount-multi debug                  # Debug coordinate conversions
"""

import argparse
import sys

from mount_driver.multi_mount import MultiMountController
from mount_driver.indi import check_indi_connection


def main():
    """Entry point for mount-multi command."""
    parser = argparse.ArgumentParser(
        description='Multi-mount control for Star Adventurer GTi arrays',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  status                    Show status of all mounts
  connect                   Auto-connect all mounts to ports
  goto AZ EL                Slew all mounts to Az/El
  sync AZ EL                Sync all mounts to Az/El
  set-location LAT LON      Set location for all mounts
  gps-location              Get location from GPS
  stop                      Emergency stop all mounts
  debug                     Debug coordinate conversions (round-trip test)
  debug AZ EL               Test conversion for specific Az/El

Examples:
  mount-multi connect
  mount-multi set-location 39.917 -105.004
  mount-multi sync 0 45
  mount-multi goto 90 45
  mount-multi goto 90 45 --mount 1  # Only mount 1
  mount-multi debug                  # Test current position
  mount-multi debug 90 45            # Test specific Az/El
""",
    )

    parser.add_argument('command', nargs='?', default='status',
                       help='Command to execute')
    parser.add_argument('args', nargs='*', help='Command arguments')
    parser.add_argument('--mount', '-m', type=int,
                       help='Target specific mount (by number)')
    parser.add_argument('--port', help='GPS serial port')
    parser.add_argument('--wait', type=int, default=30,
                       help='GPS fix timeout in seconds')

    args = parser.parse_args()

    # Check INDI server
    if not check_indi_connection():
        print('ERROR: INDI server not running. Start with ./scripts/start_server.sh')
        return 1

    controller = MultiMountController()

    # Apply saved location to all mounts
    controller.setup_location()

    if args.command == 'status':
        controller.show_status()
        return 0

    elif args.command == 'stop':
        controller.stop_all()
        return 0

    elif args.command == 'connect':
        return 0 if controller.auto_connect() else 1

    elif args.command == 'set-location' and len(args.args) == 2:
        try:
            lat = float(args.args[0])
            lon = float(args.args[1])
        except ValueError:
            print('ERROR: LAT and LON must be numbers')
            return 1
        if abs(lat) > 90 or abs(lon) > 180:
            print('ERROR: Invalid coordinates')
            return 1
        controller.setup_location(lat, lon)
        print(f'Location set: Lat={lat}  Lon={lon}')
        return 0

    elif args.command == 'gps-location':
        from mount_driver.gps import (
            get_gps_location, format_location,
            GPSNotAvailable, FixTimeoutError
        )

        print(f'Reading GPS location (timeout: {args.wait}s)...')

        def progress(sats, status):
            print(f'\r  {status} ({sats} satellites)   ', end='', flush=True)

        try:
            location = get_gps_location(
                timeout=args.wait,
                port=args.port,
                progress_callback=progress
            )
            print('\n')
            print(format_location(location))
            print()

            controller.setup_location(location['lat'], location['lon'])
            print('Location saved to config (applies to all mounts).')
            return 0

        except GPSNotAvailable as e:
            print(f'\n\nERROR: {e}')
            print('\nTroubleshooting:')
            print('  1. Connect USB GPS receiver')
            print('  2. Check device: ls /dev/ttyUSB* /dev/ttyACM*')
            print('  3. Check permissions: sudo usermod -a -G dialout $USER')
            print('  4. Specify port: mount-multi gps-location --port /dev/ttyUSB0')
            return 1

        except FixTimeoutError as e:
            print(f'\n\nERROR: {e}')
            print('\nGPS has no satellite fix. Try:')
            print('  - Move to a location with clear sky view')
            print('  - Wait longer: mount-multi gps-location --wait 120')
            return 1

    elif args.command == 'goto' and len(args.args) >= 2:
        try:
            target_az = float(args.args[0])
            target_alt = float(args.args[1])
        except ValueError:
            print('ERROR: AZ and EL must be numbers')
            return 1
        return 0 if controller.goto_all(target_az, target_alt, args.mount) else 1

    elif args.command == 'sync' and len(args.args) >= 2:
        try:
            sync_az = float(args.args[0])
            sync_alt = float(args.args[1])
        except ValueError:
            print('ERROR: AZ and EL must be numbers')
            return 1
        return 0 if controller.sync_all(sync_az, sync_alt, args.mount) else 1

    elif args.command == 'debug':
        return cmd_debug(controller, args)

    else:
        parser.print_help()
        return 1


def cmd_debug(controller, args):
    """Debug coordinate conversions with round-trip test."""
    from mount_driver.indi import indi_get

    config = controller.load_config()
    lat = config.get('lat')
    lon = config.get('lon')

    if lat is None:
        print('ERROR: Location not set. Run: mount-multi set-location LAT LON')
        return 1

    mounts = controller.discover_mounts()
    if not mounts:
        print('ERROR: No mounts discovered')
        return 1

    device = mounts[0].device
    print(f'=== Coordinate Conversion Debug (using {device}) ===\n')
    print(f'Location: Lat={lat:.4f}  Lon={lon:.4f}')

    lst = controller.get_lst(device)
    if lst is None:
        print('ERROR: Cannot read LST from mount')
        return 1
    print(f'LST: {lst:.4f} hours')
    print()

    # Get test coordinates
    if len(args.args) >= 2:
        # Use provided Az/El
        try:
            test_az = float(args.args[0])
            test_alt = float(args.args[1])
        except ValueError:
            print('ERROR: AZ and EL must be numbers')
            return 1
        print(f'Testing user-provided coordinates:')
    else:
        # Use current mount position
        indi_az = indi_get(f'{device}.HORIZONTAL_COORD.AZ')
        indi_alt = indi_get(f'{device}.HORIZONTAL_COORD.ALT')
        if indi_az and indi_alt:
            test_az = float(indi_az)
            test_alt = float(indi_alt)
            print(f'Testing current mount position (from INDI):')
        else:
            test_az = 180.0
            test_alt = 45.0
            print(f'Testing default position (INDI unavailable):')

    print(f'  Input Az/Alt: Az={test_az:.3f}  Alt={test_alt:+.3f}')
    print()

    # Step 1: Az/Alt -> RA/Dec
    result = controller.azalt_to_radec(test_az, test_alt, lat, device)
    if result is None:
        print('ERROR: azalt_to_radec conversion failed')
        return 1

    ra, dec = result
    print(f'Step 1 (Az/Alt -> RA/Dec):')
    print(f'  RA={ra:.4f}h  Dec={dec:+.4f}°')
    print()

    # Step 2: RA/Dec -> Az/Alt (round-trip)
    result2 = controller.radec_to_azalt(ra, dec, lat, device)
    if result2 is None:
        print('ERROR: radec_to_azalt conversion failed')
        return 1

    rt_az, rt_alt = result2
    print(f'Step 2 (RA/Dec -> Az/Alt round-trip):')
    print(f'  Az={rt_az:.3f}  Alt={rt_alt:+.3f}')
    print()

    # Calculate errors
    az_error = rt_az - test_az
    if az_error > 180:
        az_error -= 360
    elif az_error < -180:
        az_error += 360
    alt_error = rt_alt - test_alt

    print(f'Round-trip error:')
    print(f'  Az error: {az_error:+.4f}°')
    print(f'  Alt error: {alt_error:+.4f}°')
    print()

    # Compare with INDI-reported coordinates
    indi_ra = indi_get(f'{device}.EQUATORIAL_EOD_COORD.RA')
    indi_dec = indi_get(f'{device}.EQUATORIAL_EOD_COORD.DEC')
    indi_az = indi_get(f'{device}.HORIZONTAL_COORD.AZ')
    indi_alt = indi_get(f'{device}.HORIZONTAL_COORD.ALT')

    if indi_ra and indi_dec:
        indi_ra = float(indi_ra)
        indi_dec = float(indi_dec)
        print(f'INDI mount reports:')
        print(f'  RA/Dec: RA={indi_ra:.4f}h  Dec={indi_dec:+.4f}°')
        if indi_az and indi_alt:
            print(f'  Az/Alt: Az={float(indi_az):.3f}  Alt={float(indi_alt):+.3f}')
        print()

        # Calculate what Az/Alt the INDI RA/Dec maps to using our formula
        our_azalt = controller.radec_to_azalt(indi_ra, indi_dec, lat, device)
        if our_azalt:
            print(f'Our conversion of INDI RA/Dec to Az/Alt:')
            print(f'  Az={our_azalt[0]:.3f}  Alt={our_azalt[1]:+.3f}')
            if indi_az and indi_alt:
                diff_az = our_azalt[0] - float(indi_az)
                if diff_az > 180:
                    diff_az -= 360
                elif diff_az < -180:
                    diff_az += 360
                diff_alt = our_azalt[1] - float(indi_alt)
                print(f'  Difference from INDI Az/Alt: Az={diff_az:+.3f}°  Alt={diff_alt:+.3f}°')
                if abs(diff_az) > 1 or abs(diff_alt) > 1:
                    print()
                    print('  *** WARNING: Significant difference detected! ***')
                    print('  This suggests a coordinate convention mismatch.')

    print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
