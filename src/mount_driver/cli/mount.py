"""CLI for single mount control.

Usage:
    mount-single                      # Show current position
    mount-single goto AZ EL           # Slew to Az/El coordinates
    mount-single goto-eq RA DEC       # Slew to RA/DEC (hours, degrees)
    mount-single sync AZ EL           # Calibrate: "I am pointing at Az/El"
    mount-single sync-eq RA DEC       # Calibrate: "I am pointing at RA/DEC"
    mount-single set-location LAT LON # Set geographic location
    mount-single gps-location         # Get location from GPS receiver
    mount-single stop                 # Emergency stop all motion
    mount-single track                # Live position tracking display
    mount-single status               # Show detailed mount status
"""

import argparse
import sys
import time

from mount_driver.mount import MountController


def main():
    """Entry point for mount-single command."""
    parser = argparse.ArgumentParser(
        description='Single mount control for Star Adventurer GTi',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  (no args)                 Show current position
  goto AZ EL                Slew to Az/El coordinates
  goto-eq RA DEC            Slew to RA/DEC (hours, degrees)
  sync AZ EL                Sync to known Az/El position
  sync-eq RA DEC            Sync to known RA/DEC position
  set-location LAT LON      Set geographic location
  gps-location              Get location from GPS receiver
  stop                      Emergency stop all motion
  track                     Live position tracking
  status                    Show detailed mount status

Examples:
  mount-single set-location 39.917 -105.004
  mount-single goto 90 45
  mount-single sync-eq 2.53 89.26  # Polaris
""",
    )

    parser.add_argument('command', nargs='?', default=None,
                       help='Command to execute')
    parser.add_argument('args', nargs='*', help='Command arguments')
    parser.add_argument('--port', help='GPS serial port')
    parser.add_argument('--wait', type=int, default=30,
                       help='GPS fix timeout in seconds')

    args = parser.parse_args()

    controller = MountController()

    # Check INDI connection
    if not controller.is_connected():
        print('ERROR: INDI server not running. Start with ./scripts/start_server.sh')
        return 1

    # Load and apply saved location
    controller.setup_location()

    if args.command is None:
        # Show current position
        az, alt = controller.get_horizontal()
        ra, dec = controller.get_equatorial()

        if az is not None and abs(az) > 0.001:
            print(f'Position: Az={az:.1f}  Alt={alt:+.1f}')
            print(f'          RA={ra:.3f}h  DEC={dec:+.1f}')
        elif ra is not None:
            print(f'Position: RA={ra:.3f}h  DEC={dec:+.1f}')
            config = controller.load_config()
            if 'lat' not in config:
                print('  (Set location: mount-single set-location LAT LON)')
        else:
            print('ERROR: Cannot read position')
        return 0

    elif args.command == 'stop':
        controller.stop()
        print('All motion stopped.')
        return 0

    elif args.command == 'status':
        controller.show_status()
        return 0

    elif args.command == 'set-location' and len(args.args) == 2:
        try:
            lat = float(args.args[0])
            lon = float(args.args[1])
        except ValueError:
            print('ERROR: LAT and LON must be numbers')
            return 1
        if abs(lat) > 90:
            print('ERROR: Latitude must be between -90 and 90')
            return 1
        if abs(lon) > 180:
            print('ERROR: Longitude must be between -180 and 180')
            return 1
        controller.setup_location(lat, lon)
        print(f'Location set: Lat={lat} Lon={lon}')
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
            print('Location saved to config.')
            return 0

        except GPSNotAvailable as e:
            print(f'\n\nERROR: {e}')
            print('\nTroubleshooting:')
            print('  1. Connect USB GPS receiver')
            print('  2. Check device: ls /dev/ttyUSB* /dev/ttyACM*')
            print('  3. Check permissions: sudo usermod -a -G dialout $USER')
            print('  4. Specify port: mount-single gps-location --port /dev/ttyUSB0')
            return 1

        except FixTimeoutError as e:
            print(f'\n\nERROR: {e}')
            print('\nGPS has no satellite fix. Try:')
            print('  - Move to a location with clear sky view')
            print('  - Wait longer: mount-single gps-location --wait 120')
            return 1

    elif args.command == 'goto' and len(args.args) == 2:
        try:
            target_az = float(args.args[0])
            target_alt = float(args.args[1])
        except ValueError:
            print('ERROR: AZ and ALT must be numbers')
            return 1
        return 0 if controller.goto_horizontal(target_az, target_alt) else 1

    elif args.command == 'goto-eq' and len(args.args) == 2:
        try:
            target_ra = float(args.args[0])
            target_dec = float(args.args[1])
        except ValueError:
            print('ERROR: RA and DEC must be numbers')
            return 1
        return 0 if controller.goto_equatorial(target_ra, target_dec) else 1

    elif args.command == 'sync' and len(args.args) == 2:
        try:
            sync_az = float(args.args[0])
            sync_alt = float(args.args[1])
        except ValueError:
            print('ERROR: AZ and ALT must be numbers')
            return 1
        return 0 if controller.sync_horizontal(sync_az, sync_alt) else 1

    elif args.command == 'sync-eq' and len(args.args) == 2:
        try:
            sync_ra = float(args.args[0])
            sync_dec = float(args.args[1])
        except ValueError:
            print('ERROR: RA and DEC must be numbers')
            return 1
        return 0 if controller.sync_equatorial(sync_ra, sync_dec) else 1

    elif args.command == 'track':
        print('Live position tracking. Press Ctrl+C to stop.\n')

        try:
            while True:
                az, alt = controller.get_horizontal()
                ra, dec = controller.get_equatorial()
                ra_steps, dec_steps = controller.get_steps()

                if az is not None:
                    print(f'\rAz={az:7.2f}  Alt={alt:+7.2f}  |  '
                          f'RA={ra:7.3f}h  DEC={dec:+7.2f}  |  '
                          f'Steps: {ra_steps:.0f}/{dec_steps:.0f}    ',
                          end='', flush=True)
                time.sleep(0.5)
        except KeyboardInterrupt:
            print('\n\nStopped.')
        return 0

    else:
        parser.print_help()
        return 1


if __name__ == '__main__':
    sys.exit(main())
