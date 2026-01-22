#!/usr/bin/env python3.10
"""
Mount Calibration via Plate Solving

Calibrates mount pointing using camera plate solving with tetra3.
Bridges the ASI camera driver (tetra3 plate solving) with the mount driver
(INDI-based sync) to enable accurate GoTo functionality.

Usage:
    ./calibrate.py                          # Calibrate mount 1 with camera 0
    ./calibrate.py --mount 2 --camera CAM_1 # Specific mount and camera
    ./calibrate.py --verify                 # Solve without syncing, report error
    ./calibrate.py --all                    # Calibrate all discovered mounts
    ./calibrate.py --exposure 1.0 --gain 100 --fov 8.0  # Custom camera settings
    ./calibrate.py --dry-run                # Solve and show what would sync

Workflow:
    1. GPS calibrates mount location (existing functionality)
    2. Camera captures high-quality image
    3. tetra3 plate solves to determine actual RA/DEC pointing
    4. Mount syncs its internal coordinates with the plate solution
    5. Mount's GoTo now accurately slews to any Az/El target
"""
import argparse
import os
import sys
from dataclasses import dataclass
from typing import Optional

# Add parent directory to path for imports
_script_dir = os.path.dirname(os.path.abspath(__file__))
_asi_driver_src = os.path.join(_script_dir, '..', 'asi_driver', 'src')
sys.path.insert(0, _asi_driver_src)

# SDK path for camera initialization
_sdk_path = os.path.join(
    _script_dir, '..', 'asi_driver',
    'ASI_linux_mac_SDK_V1.41', 'lib', 'x64', 'libASICamera2.so.1.41'
)

from asi_driver.camera import (
    init_sdk,
    get_camera,
    get_camera_by_id,
    get_camera_info,
    get_camera_id,
    list_cameras_with_ids,
)
from asi_driver.capture import capture_exquisite_image
from asi_driver.registration import PlateSolution, solve_image

from point_mount import (
    sync_equatorial,
    get_equatorial,
    indi_get,
    load_config,
)
from multi_mount import discover_mounts


@dataclass
class CalibrationResult:
    """Result from mount calibration via plate solving."""
    success: bool
    camera_id: Optional[str]
    mount_id: int
    plate_solution: Optional[PlateSolution]
    ra_degrees: float
    ra_hours: float  # RA/15 for mount sync
    dec_degrees: float
    pointing_error_arcmin: Optional[float]
    message: str


def _capture_and_solve(
    camera,
    exposure_s: float,
    gain: int,
    fov_estimate: float,
) -> Optional[PlateSolution]:
    """Capture a high-quality image and plate solve it.

    Args:
        camera: Connected camera object
        exposure_s: Exposure time in seconds
        gain: Camera gain
        fov_estimate: Estimated field of view in degrees

    Returns:
        PlateSolution if successful, None if solve failed
    """
    camera_info = get_camera_info(camera)
    print(f'  Capturing {camera_info.max_width}x{camera_info.max_height} image...')

    frame, timestamp = capture_exquisite_image(
        camera,
        exposure_s=exposure_s,
        gain=gain,
    )

    print(f'  Captured {frame.shape[1]}x{frame.shape[0]} 16-bit image')
    print()
    print('Plate solving...')

    solution = solve_image(
        frame,
        fov_estimate=fov_estimate,
        distortion=(-0.2, 0.1),
    )

    return solution


def _sync_mount_from_solution(
    solution: PlateSolution,
    ra_offset: float = 0,
    dec_offset: float = 0,
) -> bool:
    """Sync mount to plate solution coordinates.

    Args:
        solution: Plate solution with RA/DEC in degrees
        ra_offset: RA offset to apply (degrees)
        dec_offset: DEC offset to apply (degrees)

    Returns:
        True if sync succeeded
    """
    # Convert RA from degrees to hours for mount sync
    ra_hours = (solution.ra + ra_offset) / 15.0
    dec_deg = solution.dec + dec_offset

    # Normalize RA to 0-24 hours
    while ra_hours < 0:
        ra_hours += 24
    while ra_hours >= 24:
        ra_hours -= 24

    return sync_equatorial(ra_hours, dec_deg)


def calibrate_mount(
    mount_id: int = 1,
    camera_id: Optional[str] = None,
    camera_index: int = 0,
    exposure_s: float = 0.5,
    gain: int = 50,
    fov_estimate: float = 10.0,
    dry_run: bool = False,
) -> CalibrationResult:
    """Calibrate a mount using plate solving.

    Captures an image, plate solves to determine actual sky coordinates,
    and syncs the mount to match.

    Args:
        mount_id: Mount number (1, 2, etc.)
        camera_id: Camera custom ID (overrides camera_index if set)
        camera_index: Camera index to use (default 0)
        exposure_s: Exposure time in seconds
        gain: Camera gain
        fov_estimate: Estimated field of view in degrees
        dry_run: If True, don't actually sync the mount

    Returns:
        CalibrationResult with success status and details
    """
    print('=== Mount Calibration ===\n')

    # Check mount connection
    device = f'Mount {mount_id}' if mount_id > 0 else 'Star Adventurer GTi'
    conn = indi_get(f'CONNECTION.CONNECT') if mount_id == 0 else None

    # For single mount, check via point_mount
    if mount_id == 1:
        from point_mount import indi_get as pm_indi_get
        conn = pm_indi_get('CONNECTION.CONNECT')

    if conn is None:
        # Try multi-mount detection
        mounts = discover_mounts()
        mount_found = any(m['id'] == mount_id for m in mounts)
        if not mount_found:
            return CalibrationResult(
                success=False,
                camera_id=camera_id,
                mount_id=mount_id,
                plate_solution=None,
                ra_degrees=0,
                ra_hours=0,
                dec_degrees=0,
                pointing_error_arcmin=None,
                message=f'Mount {mount_id} not connected. Start INDI server first.',
            )

    # Check location is set
    config = load_config()
    if 'lat' not in config:
        return CalibrationResult(
            success=False,
            camera_id=camera_id,
            mount_id=mount_id,
            plate_solution=None,
            ra_degrees=0,
            ra_hours=0,
            dec_degrees=0,
            pointing_error_arcmin=None,
            message='Location not set. Run: ./point_mount.py gps-location',
        )

    # Initialize camera SDK
    try:
        init_sdk(_sdk_path)
    except Exception as e:
        return CalibrationResult(
            success=False,
            camera_id=camera_id,
            mount_id=mount_id,
            plate_solution=None,
            ra_degrees=0,
            ra_hours=0,
            dec_degrees=0,
            pointing_error_arcmin=None,
            message=f'Failed to initialize camera SDK: {e}',
        )

    # Get camera
    try:
        if camera_id:
            camera = get_camera_by_id(camera_id)
            actual_camera_id = camera_id
        else:
            camera = get_camera(camera_index)
            actual_camera_id = get_camera_id(camera)
    except RuntimeError as e:
        return CalibrationResult(
            success=False,
            camera_id=camera_id,
            mount_id=mount_id,
            plate_solution=None,
            ra_degrees=0,
            ra_hours=0,
            dec_degrees=0,
            pointing_error_arcmin=None,
            message=f'No camera found. Check USB connection. {e}',
        )

    camera_info = get_camera_info(camera)
    camera_label = f'Camera {camera_index}'
    if actual_camera_id:
        camera_label = f'{actual_camera_id}'

    print(f'Camera: {camera_label} ({camera_info.name})')
    print(f'Mount:  Mount {mount_id} (connected)')
    print()

    # Capture and solve
    print(f'Capturing plate solving image ({exposure_s}s exposure)...')
    try:
        solution = _capture_and_solve(camera, exposure_s, gain, fov_estimate)
    except Exception as e:
        camera.close()
        return CalibrationResult(
            success=False,
            camera_id=actual_camera_id,
            mount_id=mount_id,
            plate_solution=None,
            ra_degrees=0,
            ra_hours=0,
            dec_degrees=0,
            pointing_error_arcmin=None,
            message=f'Capture failed: {e}',
        )

    camera.close()

    if solution is None:
        return CalibrationResult(
            success=False,
            camera_id=actual_camera_id,
            mount_id=mount_id,
            plate_solution=None,
            ra_degrees=0,
            ra_hours=0,
            dec_degrees=0,
            pointing_error_arcmin=None,
            message='Plate solve failed. Check sky conditions, try longer exposure.',
        )

    ra_hours = solution.ra / 15.0
    print(f'  RA:  {solution.ra:.2f} ({ra_hours:.3f}h)')
    print(f'  DEC: {solution.dec:+.2f}')
    print(f'  FOV: {solution.fov:.2f}')
    if solution.num_matches:
        print(f'  Matched: {solution.num_matches} stars')
    print()

    # Calculate pointing error before sync
    pointing_error_arcmin = None
    current_ra, current_dec = get_equatorial()
    if current_ra is not None:
        # Convert mount RA (hours) to degrees for comparison
        mount_ra_deg = current_ra * 15.0
        ra_diff = abs(mount_ra_deg - solution.ra)
        if ra_diff > 180:
            ra_diff = 360 - ra_diff
        dec_diff = abs(current_dec - solution.dec)
        # Approximate angular separation in arcminutes
        pointing_error_arcmin = ((ra_diff ** 2 + dec_diff ** 2) ** 0.5) * 60

    # Sync mount
    if dry_run:
        print('[DRY RUN] Would sync mount...')
        print(f'  Mount reports: RA={current_ra:.3f}h  DEC={current_dec:+.2f}')
        print(f'  Would sync to: RA={ra_hours:.3f}h  DEC={solution.dec:+.2f}')
        if pointing_error_arcmin:
            print(f'  Pointing error: {pointing_error_arcmin:.1f} arcmin')
        message = 'Dry run complete. Mount not synced.'
    else:
        print('Syncing mount...')
        if current_ra is not None:
            print(f'  Before: RA={current_ra:.3f}h  DEC={current_dec:+.2f}')

        sync_success = _sync_mount_from_solution(solution)

        if sync_success:
            new_ra, new_dec = get_equatorial()
            if new_ra is not None:
                print(f'  After:  RA={new_ra:.3f}h  DEC={new_dec:+.2f}')
            print()
            print('Calibration successful!')
            message = 'Calibration successful.'
        else:
            return CalibrationResult(
                success=False,
                camera_id=actual_camera_id,
                mount_id=mount_id,
                plate_solution=solution,
                ra_degrees=solution.ra,
                ra_hours=ra_hours,
                dec_degrees=solution.dec,
                pointing_error_arcmin=pointing_error_arcmin,
                message='Sync command failed.',
            )

    return CalibrationResult(
        success=True,
        camera_id=actual_camera_id,
        mount_id=mount_id,
        plate_solution=solution,
        ra_degrees=solution.ra,
        ra_hours=ra_hours,
        dec_degrees=solution.dec,
        pointing_error_arcmin=pointing_error_arcmin,
        message=message,
    )


def verify_calibration(
    mount_id: int = 1,
    camera_id: Optional[str] = None,
    camera_index: int = 0,
    exposure_s: float = 0.5,
    gain: int = 50,
    fov_estimate: float = 10.0,
) -> CalibrationResult:
    """Verify mount calibration by plate solving without syncing.

    Captures and plate solves to compare actual sky position
    with what the mount reports.

    Args:
        mount_id: Mount number (1, 2, etc.)
        camera_id: Camera custom ID (overrides camera_index if set)
        camera_index: Camera index to use
        exposure_s: Exposure time in seconds
        gain: Camera gain
        fov_estimate: Estimated field of view in degrees

    Returns:
        CalibrationResult with pointing error measurement
    """
    print('=== Calibration Verification ===\n')

    result = calibrate_mount(
        mount_id=mount_id,
        camera_id=camera_id,
        camera_index=camera_index,
        exposure_s=exposure_s,
        gain=gain,
        fov_estimate=fov_estimate,
        dry_run=True,
    )

    if result.success and result.pointing_error_arcmin is not None:
        print()
        if result.pointing_error_arcmin < 5:
            print(f'Calibration verified: {result.pointing_error_arcmin:.1f} arcmin error (excellent)')
        elif result.pointing_error_arcmin < 30:
            print(f'Calibration verified: {result.pointing_error_arcmin:.1f} arcmin error (good)')
        else:
            print(f'Calibration needed: {result.pointing_error_arcmin:.1f} arcmin error (recalibrate)')

    return result


def calibrate_all_mounts(
    pairs: Optional[dict[int, int]] = None,
    camera_id_map: Optional[dict[int, str]] = None,
    exposure_s: float = 0.5,
    gain: int = 50,
    fov_estimate: float = 10.0,
    dry_run: bool = False,
) -> dict[int, CalibrationResult]:
    """Calibrate all discovered mounts.

    By default, pairs camera index N with mount N.

    Args:
        pairs: Optional mapping of mount_id -> camera_index
        camera_id_map: Optional mapping of mount_id -> camera_id
        exposure_s: Exposure time in seconds
        gain: Camera gain
        fov_estimate: Estimated field of view in degrees
        dry_run: If True, don't actually sync mounts

    Returns:
        Dict mapping mount_id to CalibrationResult
    """
    print('=== Multi-Mount Calibration ===\n')

    mounts = discover_mounts()
    if not mounts:
        print('No mounts discovered. Start INDI server first.')
        return {}

    print(f'Found {len(mounts)} mount(s)\n')

    # Build default pairs if not provided
    if pairs is None:
        pairs = {m['id']: m['id'] - 1 for m in mounts}  # Mount N -> Camera N-1

    results = {}

    for mount in mounts:
        mount_id = mount['id']
        camera_index = pairs.get(mount_id, mount_id - 1)
        camera_id = camera_id_map.get(mount_id) if camera_id_map else None

        print(f'--- Mount {mount_id} ---\n')

        result = calibrate_mount(
            mount_id=mount_id,
            camera_id=camera_id,
            camera_index=camera_index,
            exposure_s=exposure_s,
            gain=gain,
            fov_estimate=fov_estimate,
            dry_run=dry_run,
        )

        results[mount_id] = result
        print()

    # Summary
    print('=== Summary ===')
    for mount_id, result in results.items():
        status = 'OK' if result.success else 'FAILED'
        print(f'  Mount {mount_id}: {status} - {result.message}')

    return results


def main():
    parser = argparse.ArgumentParser(
        description='Calibrate mount pointing via plate solving',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ./calibrate.py                          # Calibrate mount 1 with camera 0
  ./calibrate.py --mount 2 --camera CAM_1 # Specific mount and camera
  ./calibrate.py --verify                 # Check calibration without syncing
  ./calibrate.py --all                    # Calibrate all mounts
  ./calibrate.py --dry-run                # Show what would happen
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
        '--list-cameras',
        action='store_true',
        help='List connected cameras and exit',
    )

    args = parser.parse_args()

    # List cameras mode
    if args.list_cameras:
        try:
            init_sdk(_sdk_path)
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

    # Determine camera ID or index
    camera_id = None
    camera_index = args.camera_index

    if args.camera:
        # Check if it's a number (index) or string (ID)
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
        )
        return 0 if result.success else 1

    elif args.all:
        results = calibrate_all_mounts(
            exposure_s=args.exposure,
            gain=args.gain,
            fov_estimate=args.fov,
            dry_run=args.dry_run,
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
        )
        if not result.success:
            print(f'\nCalibration failed: {result.message}')
        return 0 if result.success else 1


if __name__ == '__main__':
    sys.exit(main())
