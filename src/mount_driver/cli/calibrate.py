"""CLI for mount calibration via plate solving.

Usage:
    mount-calibrate                          # Calibrate mount 1 with camera 0
    mount-calibrate --mount 2 --camera CAM_1 # Specific mount and camera
    mount-calibrate --verify                 # Solve without syncing, report error
    mount-calibrate --all                    # Calibrate all discovered mounts
    mount-calibrate --exposure 1.0 --gain 100 --fov 8.0  # Custom camera settings
    mount-calibrate --dry-run                # Solve and show what would sync
"""

import argparse
import sys

from mount_driver.calibration import (
    calibrate_mount,
    calibrate_all_mounts,
    verify_calibration,
    solve_from_file,
)


def main():
    """Entry point for mount-calibrate command."""
    parser = argparse.ArgumentParser(
        description='Calibrate mount pointing via plate solving',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  mount-calibrate                          # Calibrate mount 1 with camera 0
  mount-calibrate --mount 2 --camera CAM_1 # Specific mount and camera
  mount-calibrate --verify                 # Check calibration without syncing
  mount-calibrate --all                    # Calibrate all mounts
  mount-calibrate --dry-run                # Show what would happen
""",
    )

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        '--verify',
        action='store_true',
        help='Verify calibration without syncing',
    )
    mode_group.add_argument(
        '--all',
        action='store_true',
        help='Calibrate all discovered mounts',
    )

    # Mount/camera selection
    parser.add_argument(
        '--mount', '-m',
        type=int,
        default=1,
        help='Mount number to calibrate (default: 1)',
    )
    parser.add_argument(
        '--camera', '-c',
        type=str,
        help='Camera ID (e.g., CAM_1) or index',
    )
    parser.add_argument(
        '--camera-index',
        type=int,
        default=0,
        help='Camera index (default: 0)',
    )

    # Camera settings
    parser.add_argument(
        '--exposure', '-e',
        type=float,
        default=0.5,
        help='Exposure time in seconds (default: 0.5)',
    )
    parser.add_argument(
        '--gain', '-g',
        type=int,
        default=50,
        help='Camera gain (default: 50)',
    )
    parser.add_argument(
        '--fov',
        type=float,
        default=10.0,
        help='Estimated field of view in degrees (default: 10.0)',
    )

    # Options
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Solve and show what would sync, but do not sync',
    )
    parser.add_argument(
        '--sdk-path',
        help='Path to ZWO SDK library (auto-detected if not specified)',
    )
    parser.add_argument(
        '--list-cameras',
        action='store_true',
        help='List connected cameras and exit',
    )
    parser.add_argument(
        '--test-image',
        type=str,
        help='Path to saved image for testing plate solve (zarr dir, TIFF, FITS, PNG)',
    )

    args = parser.parse_args()

    # List cameras mode
    if args.list_cameras:
        try:
            from asi_driver.camera import init_sdk, list_cameras_with_ids
            from pathlib import Path

            project_root = Path(__file__).parent.parent.parent.parent
            sdk_path = args.sdk_path or str(
                project_root / 'asi_driver' / 'ASI_linux_mac_SDK_V1.41' /
                'lib' / 'x64' / 'libASICamera2.so.1.41'
            )

            init_sdk(sdk_path)
            cameras = list_cameras_with_ids()
            if cameras:
                print('Connected cameras:')
                for cam in cameras:
                    id_str = f' (ID: {cam["camera_id"]})' if cam['camera_id'] else ''
                    print(f'  {cam["index"]}: {cam["name"]}{id_str}')
            else:
                print('No cameras found')
        except Exception as e:
            print(f'Error: {e}')
        return 0

    # Test image mode (no mount/camera needed)
    if args.test_image:
        result = solve_from_file(
            image_path=args.test_image,
            fov_estimate=args.fov,
        )
        if not result.success:
            print(f'\nSolve failed: {result.message}')
        return 0 if result.success else 1

    # Determine camera ID or index
    camera_id = None
    camera_index = args.camera_index

    if args.camera:
        try:
            camera_index = int(args.camera)
        except ValueError:
            camera_id = args.camera

    # Run appropriate mode
    if args.verify:
        result = verify_calibration(
            mount_id=args.mount,
            camera_id=camera_id,
            camera_index=camera_index,
            exposure_s=args.exposure,
            gain=args.gain,
            fov_estimate=args.fov,
            sdk_path=args.sdk_path,
        )
        return 0 if result.success else 1

    elif args.all:
        results = calibrate_all_mounts(
            exposure_s=args.exposure,
            gain=args.gain,
            fov_estimate=args.fov,
            dry_run=args.dry_run,
            sdk_path=args.sdk_path,
        )
        return 0 if all(r.success for r in results.values()) else 1

    else:
        result = calibrate_mount(
            mount_id=args.mount,
            camera_id=camera_id,
            camera_index=camera_index,
            exposure_s=args.exposure,
            gain=args.gain,
            fov_estimate=args.fov,
            dry_run=args.dry_run,
            sdk_path=args.sdk_path,
        )
        if not result.success:
            print(f'\nCalibration failed: {result.message}')
        return 0 if result.success else 1


if __name__ == '__main__':
    sys.exit(main())
