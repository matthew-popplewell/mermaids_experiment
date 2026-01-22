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

Examples:
  mount-multi connect
  mount-multi set-location 39.917 -105.004
  mount-multi sync 0 45
  mount-multi goto 90 45
  mount-multi goto 90 45 --mount 1  # Only mount 1
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

    else:
        parser.print_help()
        return 1


if __name__ == '__main__':
    sys.exit(main())
