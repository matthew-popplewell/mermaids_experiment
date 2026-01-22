"""CLI for complete observation workflow.

Orchestrates the full observation sequence:
1. Verify INDI server running
2. Get GPS location
3. Calibrate mounts via plate solving
4. Slew all mounts to target Az/El
5. Prompt for focusing
6. Run asi-burst on all cameras

Usage:
    mount-observe --target AZ EL --duration SECS --output DIR
    mount-observe --target 90 45 --duration 60 --output ./data/ --skip-gps
    mount-observe --target 180 30 --duration 300 --output ./obs/ --cameras 1,2,3,4
"""

import argparse
import subprocess
import sys
import time

from mount_driver.multi_mount import MultiMountController, discover_mounts
from mount_driver.indi import check_indi_connection


def main():
    """Entry point for mount-observe command."""
    parser = argparse.ArgumentParser(
        description='Complete observation workflow orchestrator',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Workflow:
  1. Verify INDI server running
  2. Get GPS location (or skip with --skip-gps)
  3. Calibrate mounts via plate solving (or skip with --skip-calibrate)
  4. Slew all mounts to target Az/El
  5. Prompt for focusing (or skip with --skip-focus)
  6. Run asi-burst on all cameras

Examples:
  mount-observe --target 90 45 --duration 60 --output ./data/
  mount-observe --target 180 30 --duration 300 --output ./obs/ --skip-calibrate
  mount-observe --target 90 45 --duration 60 --output ./data/ --cameras 1,2,3,4
""",
    )

    # Required arguments
    parser.add_argument(
        '--target', '-t',
        nargs=2,
        type=float,
        required=True,
        metavar=('AZ', 'EL'),
        help='Target Az/El coordinates in degrees',
    )
    parser.add_argument(
        '--duration', '-d',
        type=float,
        required=True,
        help='Burst capture duration in seconds',
    )
    parser.add_argument(
        '--output', '-o',
        type=str,
        required=True,
        help='Output directory for captured data',
    )

    # Optional workflow skips
    parser.add_argument(
        '--skip-gps',
        action='store_true',
        help='Skip GPS location acquisition',
    )
    parser.add_argument(
        '--skip-calibrate',
        action='store_true',
        help='Skip plate solving calibration',
    )
    parser.add_argument(
        '--skip-focus',
        action='store_true',
        help='Skip focus prompt',
    )
    parser.add_argument(
        '--skip-slew',
        action='store_true',
        help='Skip mount slew (assume already pointed)',
    )

    # Camera settings
    parser.add_argument(
        '--cameras',
        type=str,
        help='Comma-separated camera IDs (e.g., 1,2,3,4)',
    )
    parser.add_argument(
        '--exposure',
        type=int,
        default=20000,
        help='Burst exposure in microseconds (default: 20000)',
    )
    parser.add_argument(
        '--gain',
        type=int,
        default=600,
        help='Camera gain (default: 600)',
    )

    # Calibration settings
    parser.add_argument(
        '--fov',
        type=float,
        default=10.0,
        help='Field of view estimate for plate solving (default: 10.0)',
    )

    args = parser.parse_args()

    target_az, target_el = args.target

    print('=' * 60)
    print('MERMAIDS Observation Workflow')
    print('=' * 60)
    print()
    print(f'Target:   Az={target_az:.1f}  El={target_el:+.1f}')
    print(f'Duration: {args.duration}s')
    print(f'Output:   {args.output}')
    print()

    # Step 1: Verify INDI server
    print('Step 1: Checking INDI server...')
    if not check_indi_connection():
        print('ERROR: INDI server not running.')
        print('  Start with: ./scripts/start_server.sh')
        return 1
    print('  INDI server running')
    print()

    controller = MultiMountController()
    mounts = discover_mounts()

    if not mounts:
        print('ERROR: No mounts discovered')
        return 1

    print(f'  Found {len(mounts)} mount(s)')
    print()

    # Step 2: GPS location
    if not args.skip_gps:
        print('Step 2: Getting GPS location...')
        try:
            from mount_driver.gps import get_gps_location, format_location

            def progress(sats, status):
                print(f'\r  {status} ({sats} satellites)   ', end='', flush=True)

            location = get_gps_location(timeout=30, progress_callback=progress)
            print('\n')
            print(format_location(location))
            print()
            controller.setup_location(location['lat'], location['lon'])
            print('  Location set for all mounts')
        except Exception as e:
            print(f'\n  Warning: GPS failed: {e}')
            print('  Continuing with saved location...')
            controller.setup_location()
        print()
    else:
        print('Step 2: Skipping GPS (using saved location)')
        controller.setup_location()
        print()

    # Step 3: Calibration
    if not args.skip_calibrate:
        print('Step 3: Calibrating mounts via plate solving...')
        try:
            from mount_driver.calibration import calibrate_all_mounts

            results = calibrate_all_mounts(
                fov_estimate=args.fov,
                dry_run=False,
            )

            success_count = sum(1 for r in results.values() if r.success)
            print(f'  Calibrated {success_count}/{len(results)} mount(s)')
        except Exception as e:
            print(f'  Warning: Calibration failed: {e}')
            print('  Continuing without calibration...')
        print()
    else:
        print('Step 3: Skipping calibration')
        print()

    # Step 4: Slew to target
    if not args.skip_slew:
        print('Step 4: Slewing to target...')
        success = controller.goto_all(target_az, target_el)
        if not success:
            print('  Warning: Some mounts may not have reached target')
        print()
    else:
        print('Step 4: Skipping slew (assuming already pointed)')
        print()

    # Step 5: Focus
    if not args.skip_focus:
        print('Step 5: Focus adjustment')
        print('  Run asi-focus to adjust camera focus.')
        print()
        input('  Press Enter when focus is complete...')
        print()
    else:
        print('Step 5: Skipping focus prompt')
        print()

    # Step 6: Burst capture
    print('Step 6: Starting burst capture...')
    print()

    # Build asi-burst command
    cmd = [
        'asi-burst',
        '-d', str(args.duration),
        '-o', args.output,
        '-e', str(args.exposure),
        '-g', str(args.gain),
        '--no-solve',
    ]

    if args.cameras:
        cmd.extend(['--cameras', args.cameras])

    print(f'Running: {" ".join(cmd)}')
    print()

    try:
        result = subprocess.run(cmd)
        return result.returncode
    except FileNotFoundError:
        print('ERROR: asi-burst command not found.')
        print('  Make sure the package is installed: uv sync')
        return 1
    except KeyboardInterrupt:
        print('\n\nObservation interrupted')
        controller.stop_all()
        return 0


if __name__ == '__main__':
    sys.exit(main())
