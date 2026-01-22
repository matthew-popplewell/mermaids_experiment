"""Mount Calibration via Plate Solving.

Calibrates mount pointing using camera plate solving with tetra3.
Bridges the ASI camera driver (tetra3 plate solving) with the mount driver
(INDI-based sync) to enable accurate GoTo functionality.

Example usage:
    from mount_driver.calibration import calibrate_mount, calibrate_all_mounts

    result = calibrate_mount(mount_id=1, camera_index=0)
    if result.success:
        print(f'Calibrated: RA={result.ra_hours:.3f}h DEC={result.dec_degrees:+.2f}')
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from mount_driver.mount import MountController, sync_equatorial, get_equatorial, load_config
from mount_driver.multi_mount import discover_mounts
from mount_driver.indi import indi_get


# SDK path for camera initialization (relative to project root)
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_SDK_PATH = _PROJECT_ROOT / 'asi_driver' / 'ASI_linux_mac_SDK_V1.41' / 'lib' / 'x64' / 'libASICamera2.so.1.41'


@dataclass
class CalibrationResult:
    """Result from mount calibration via plate solving."""
    success: bool
    camera_id: Optional[str]
    mount_id: int
    plate_solution: Optional[object]  # PlateSolution from asi_driver
    ra_degrees: float
    ra_hours: float
    dec_degrees: float
    pointing_error_arcmin: Optional[float]
    message: str


def _capture_and_solve(
    camera,
    exposure_s: float,
    gain: int,
    fov_estimate: float,
):
    """Capture a high-quality image and plate solve it.

    Args:
        camera: Connected camera object
        exposure_s: Exposure time in seconds
        gain: Camera gain
        fov_estimate: Estimated field of view in degrees

    Returns:
        PlateSolution if successful, None if solve failed
    """
    from asi_driver.camera import get_camera_info
    from asi_driver.capture import capture_exquisite_image
    from asi_driver.registration import solve_image

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
    solution,
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
    sdk_path: Optional[str] = None,
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
        sdk_path: Path to ASI SDK (auto-detected if None)

    Returns:
        CalibrationResult with success status and details
    """
    from asi_driver.camera import (
        init_sdk,
        get_camera,
        get_camera_by_id,
        get_camera_info,
        get_camera_id,
    )

    print('=== Mount Calibration ===\n')

    # Check mount connection
    device = f'Mount {mount_id}' if mount_id > 0 else 'Star Adventurer GTi'
    conn = indi_get(f'{device}.CONNECTION.CONNECT')

    if conn is None:
        # Try multi-mount detection
        mounts = discover_mounts()
        mount_found = any(m.id == mount_id for m in mounts)
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
            message='Location not set. Run: mount-single gps-location',
        )

    # Initialize camera SDK
    actual_sdk_path = sdk_path or str(_SDK_PATH)
    try:
        init_sdk(actual_sdk_path)
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
        mount_ra_deg = current_ra * 15.0
        ra_diff = abs(mount_ra_deg - solution.ra)
        if ra_diff > 180:
            ra_diff = 360 - ra_diff
        dec_diff = abs(current_dec - solution.dec)
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
    sdk_path: Optional[str] = None,
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
        sdk_path: Path to ASI SDK

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
        sdk_path=sdk_path,
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
    pairs: Optional[Dict[int, int]] = None,
    camera_id_map: Optional[Dict[int, str]] = None,
    exposure_s: float = 0.5,
    gain: int = 50,
    fov_estimate: float = 10.0,
    dry_run: bool = False,
    sdk_path: Optional[str] = None,
) -> Dict[int, CalibrationResult]:
    """Calibrate all discovered mounts.

    By default, pairs camera index N with mount N.

    Args:
        pairs: Optional mapping of mount_id -> camera_index
        camera_id_map: Optional mapping of mount_id -> camera_id
        exposure_s: Exposure time in seconds
        gain: Camera gain
        fov_estimate: Estimated field of view in degrees
        dry_run: If True, don't actually sync mounts
        sdk_path: Path to ASI SDK

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
        pairs = {m.id: m.id - 1 for m in mounts}

    results = {}

    for mount in mounts:
        mount_id = mount.id
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
            sdk_path=sdk_path,
        )

        results[mount_id] = result
        print()

    # Summary
    print('=== Summary ===')
    for mount_id, result in results.items():
        status = 'OK' if result.success else 'FAILED'
        print(f'  Mount {mount_id}: {status} - {result.message}')

    return results
