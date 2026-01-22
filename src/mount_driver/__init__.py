"""Mount driver package for Star Adventurer GTi telescope mounts.

This package provides control for single and multiple co-located telescope mounts
using the INDI protocol.

Main modules:
    mount: Single mount control (Az/El, RA/DEC, sync, GoTo)
    multi_mount: Multi-mount control for co-located arrays
    calibration: Plate solving calibration via tetra3
    gps: GPS location via serial connection
    diagnostics: System diagnostics and troubleshooting

CLI commands (installed via pyproject.toml):
    mount-single: Single mount control
    mount-multi: Multi-mount control
    mount-calibrate: Plate solving calibration
    mount-diagnose: System diagnostics
    mount-observe: Full observation workflow
"""

from mount_driver.mount import (
    MountController,
    get_horizontal,
    get_equatorial,
    goto_horizontal,
    goto_equatorial,
    sync_horizontal,
    sync_equatorial,
    stop_all,
    setup_location,
)

from mount_driver.multi_mount import (
    MultiMountController,
    discover_mounts,
    goto_all_mounts,
    sync_all_mounts,
    stop_all_mounts,
)

from mount_driver.gps import (
    GPSReader,
    GPSLocation,
    get_gps_location,
    gps_available,
    format_location,
    GPSError,
    GPSNotAvailable,
    NoFixError,
    FixTimeoutError,
)

from mount_driver.calibration import (
    CalibrationResult,
    calibrate_mount,
    calibrate_all_mounts,
    verify_calibration,
)

from mount_driver.diagnostics import (
    check_mount_hardware,
    check_indi_server,
)

__version__ = "0.1.0"
__all__ = [
    # Mount control
    "MountController",
    "get_horizontal",
    "get_equatorial",
    "goto_horizontal",
    "goto_equatorial",
    "sync_horizontal",
    "sync_equatorial",
    "stop_all",
    "setup_location",
    # Multi-mount
    "MultiMountController",
    "discover_mounts",
    "goto_all_mounts",
    "sync_all_mounts",
    "stop_all_mounts",
    # GPS
    "GPSReader",
    "GPSLocation",
    "get_gps_location",
    "gps_available",
    "format_location",
    "GPSError",
    "GPSNotAvailable",
    "NoFixError",
    "FixTimeoutError",
    # Calibration
    "CalibrationResult",
    "calibrate_mount",
    "calibrate_all_mounts",
    "verify_calibration",
    # Diagnostics
    "check_mount_hardware",
    "check_indi_server",
]
