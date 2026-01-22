"""Single mount control for Star Adventurer GTi.

Controls the mount using INDI GoTo functionality for Az/El positioning.
Both RA and DEC motors are controlled via the GoTo interface.

Example usage:
    from mount_driver.mount import MountController

    controller = MountController()
    controller.setup_location(39.917, -105.004)
    controller.goto_horizontal(90, 45)  # Az=90, El=45
"""

import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from mount_driver.indi import indi_get, indi_set
from mount_driver.pointing_model import PointingModel, compute_correction


# Default device name for single mount mode
DEFAULT_DEVICE = 'Star Adventurer GTi'

# Configuration file location
CONFIG_DIR = Path(__file__).parent
CONFIG_FILE = CONFIG_DIR / '.mount_config.json'

# Mount constants
STEPS_PER_360_RA = 3628800.0   # Axis 1 (RA)
STEPS_PER_360_DEC = 2903040.0  # Axis 2 (Dec)

# GoTo parameters
TOLERANCE_DEG = 0.5
GOTO_TIMEOUT = 120


@dataclass
class MountPosition:
    """Current mount position."""
    az: Optional[float] = None
    alt: Optional[float] = None
    ra: Optional[float] = None
    dec: Optional[float] = None
    ra_steps: Optional[float] = None
    dec_steps: Optional[float] = None


class MountController:
    """Controller for a single Star Adventurer GTi mount."""

    def __init__(self, device: str = DEFAULT_DEVICE):
        """Initialize mount controller.

        Args:
            device: INDI device name (default: 'Star Adventurer GTi')
        """
        self.device = device
        self._config_file = CONFIG_FILE

    def _indi_get(self, prop: str) -> Optional[str]:
        """Get INDI property for this mount."""
        return indi_get(f'{self.device}.{prop}')

    def _indi_set(self, prop: str, value: Optional[str] = None):
        """Set INDI property for this mount."""
        if value is not None:
            indi_set(f'{self.device}.{prop}', value)
        else:
            indi_set(f'{self.device}.{prop}')

    def is_connected(self) -> bool:
        """Check if mount is connected via INDI."""
        conn = self._indi_get('CONNECTION.CONNECT')
        return conn is not None

    def get_steps(self) -> Tuple[Optional[float], Optional[float]]:
        """Get current step positions."""
        ra = self._indi_get('CURRENTSTEPPERS.RAStepsCurrent')
        dec = self._indi_get('CURRENTSTEPPERS.DEStepsCurrent')
        if ra and dec:
            return float(ra), float(dec)
        return None, None

    def get_horizontal(self) -> Tuple[Optional[float], Optional[float]]:
        """Get current Az/Alt position."""
        az = self._indi_get('HORIZONTAL_COORD.AZ')
        alt = self._indi_get('HORIZONTAL_COORD.ALT')
        if az and alt:
            return float(az), float(alt)
        return None, None

    def get_equatorial(self) -> Tuple[Optional[float], Optional[float]]:
        """Get current RA/DEC position."""
        ra = self._indi_get('EQUATORIAL_EOD_COORD.RA')
        dec = self._indi_get('EQUATORIAL_EOD_COORD.DEC')
        if ra and dec:
            return float(ra), float(dec)
        return None, None

    def get_position(self) -> MountPosition:
        """Get complete mount position."""
        az, alt = self.get_horizontal()
        ra, dec = self.get_equatorial()
        ra_steps, dec_steps = self.get_steps()
        return MountPosition(az=az, alt=alt, ra=ra, dec=dec,
                           ra_steps=ra_steps, dec_steps=dec_steps)

    def get_lst(self) -> Optional[float]:
        """Get local sidereal time from INDI (in hours)."""
        lst = self._indi_get('TIME_LST.LST')
        if lst:
            return float(lst)
        return None

    def load_config(self) -> dict:
        """Load configuration (geographic location)."""
        if self._config_file.exists():
            try:
                with open(self._config_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    def save_config(self, config: dict):
        """Save configuration."""
        with open(self._config_file, 'w') as f:
            json.dump(config, f, indent=2)

    def setup_location(self, lat: Optional[float] = None, lon: Optional[float] = None) -> bool:
        """Set geographic coordinates. Required for Az/Alt GoTo.

        Args:
            lat: Latitude in degrees (-90 to 90)
            lon: Longitude in degrees (-180 to 180)

        Returns:
            True if location is set
        """
        config = self.load_config()

        if lat is not None and lon is not None:
            config['lat'] = lat
            config['lon'] = lon
            self.save_config(config)

        lat = config.get('lat')
        lon = config.get('lon')

        if lat is None or lon is None:
            return False

        self._indi_set(f'GEOGRAPHIC_COORD.LAT={lat};LONG={lon}')
        return True

    def azalt_to_radec(self, az: float, alt: float, lat: float) -> Optional[Tuple[float, float]]:
        """Convert Az/Alt to RA/DEC using current LST.

        Args:
            az: Azimuth in degrees (0=North, 90=East)
            alt: Altitude in degrees
            lat: Observer latitude in degrees

        Returns:
            (ra_hours, dec_degrees) or None if conversion fails
        """
        lst = self.get_lst()
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

    def stop(self):
        """Stop all motion immediately using abort."""
        self._indi_set('TELESCOPE_ABORT_MOTION.ABORT', 'On')

    def wait_for_goto(self, timeout: float = GOTO_TIMEOUT, show_progress: bool = True) -> bool:
        """Wait for GoTo to complete by monitoring step changes."""
        start = time.time()
        last_ra_steps = None
        last_dec_steps = None
        stable_count = 0
        moving_detected = False

        while time.time() - start < timeout:
            ra_steps, dec_steps = self.get_steps()
            az, alt = self.get_horizontal()
            ra, dec = self.get_equatorial()

            if show_progress and az is not None:
                elapsed = time.time() - start
                print(f'\r  [{elapsed:4.0f}s] Az={az:6.1f}  Alt={alt:+6.1f}  '
                      f'RA={ra:.2f}h  DEC={dec:+.1f}  ', end='', flush=True)

            if last_ra_steps is not None and ra_steps is not None:
                ra_delta = abs(ra_steps - last_ra_steps)
                dec_delta = abs(dec_steps - last_dec_steps) if dec_steps else 0

                if ra_delta > 100 or dec_delta > 100:
                    moving_detected = True
                    stable_count = 0
                else:
                    stable_count += 1
                    if moving_detected and stable_count >= 4:
                        if show_progress:
                            print(' Done!')
                        return True
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

    def goto_horizontal(self, target_az: float, target_alt: float) -> bool:
        """Slew to target Az/Alt position by converting to RA/DEC.

        Args:
            target_az: Target azimuth in degrees
            target_alt: Target altitude in degrees

        Returns:
            True if slew completed successfully
        """
        config = self.load_config()
        lat = config.get('lat')
        if lat is None:
            print('ERROR: Location not set.')
            print('  Run: mount-single set-location LAT LON')
            return False

        current_az, current_alt = self.get_horizontal()
        if current_az is None:
            print('ERROR: Cannot read position')
            return False

        print(f'Current: Az={current_az:.1f}  Alt={current_alt:+.1f}')
        print(f'Target:  Az={target_az:.1f}  Alt={target_alt:+.1f}')

        if target_alt < -5:
            print(f'ERROR: Target altitude {target_alt:.1f} is below horizon')
            return False

        result = self.azalt_to_radec(target_az, target_alt, lat)
        if result is None:
            print('ERROR: Cannot convert coordinates (LST unavailable)')
            return False

        target_ra, target_dec = result
        print(f'(Converted to RA={target_ra:.2f}h  DEC={target_dec:+.1f})')

        # Apply pointing model correction if calibrated
        model_data = config.get('pointing_model')
        if model_data:
            model = PointingModel.from_dict(model_data)
            lst = self.get_lst()
            if lst is not None and not model.is_zero():
                target_ra, target_dec = compute_correction(target_ra, target_dec, lst, model)
                print(f'(Corrected to RA={target_ra:.2f}h  DEC={target_dec:+.1f})')

        self._indi_set('ON_COORD_SET.SLEW', 'On')
        time.sleep(0.1)

        print('Slewing...', flush=True)
        self._indi_set(f'EQUATORIAL_EOD_COORD.RA={target_ra};DEC={target_dec}')

        time.sleep(0.5)

        if self.wait_for_goto():
            final_az, final_alt = self.get_horizontal()
            print(f'Reached: Az={final_az:.1f}  Alt={final_alt:+.1f}')
            return True
        else:
            self.stop()
            return False

    def goto_equatorial(self, target_ra: float, target_dec: float) -> bool:
        """Slew to target RA/DEC position using GoTo.

        Args:
            target_ra: Target RA in hours
            target_dec: Target DEC in degrees

        Returns:
            True if slew completed successfully
        """
        current_ra, current_dec = self.get_equatorial()
        if current_ra is None:
            print('ERROR: Cannot read position')
            return False

        print(f'Current: RA={current_ra:.3f}h  DEC={current_dec:+.2f}')
        print(f'Target:  RA={target_ra:.3f}h  DEC={target_dec:+.2f}')

        self._indi_set('ON_COORD_SET.SLEW', 'On')
        time.sleep(0.1)

        print('Slewing...', flush=True)
        self._indi_set(f'EQUATORIAL_EOD_COORD.RA={target_ra};DEC={target_dec}')

        time.sleep(0.5)

        if self.wait_for_goto():
            final_ra, final_dec = self.get_equatorial()
            print(f'Reached: RA={final_ra:.3f}h  DEC={final_dec:+.2f}')
            return True
        else:
            self.stop()
            return False

    def sync_equatorial(self, sync_ra: float, sync_dec: float) -> bool:
        """Sync mount to known RA/DEC coordinates (calibration).

        Args:
            sync_ra: Known RA in hours
            sync_dec: Known DEC in degrees

        Returns:
            True if sync succeeded
        """
        current_ra, current_dec = self.get_equatorial()
        if current_ra is None:
            print('ERROR: Cannot read position')
            return False

        print(f'Before sync: RA={current_ra:.3f}h  DEC={current_dec:+.2f}')
        print(f'Syncing to:  RA={sync_ra:.3f}h  DEC={sync_dec:+.2f}')

        # Enable tracking and standard sync mode - required for sync on Star Adventurer GTi
        self._indi_set('TELESCOPE_TRACK_STATE.TRACK_ON', 'On')
        self._indi_set('ALIGNSYNCMODE.ALIGNSTANDARDSYNC', 'On')
        time.sleep(0.3)

        self._indi_set('ON_COORD_SET.SYNC', 'On')
        time.sleep(0.1)

        self._indi_set(f'EQUATORIAL_EOD_COORD.RA={sync_ra};DEC={sync_dec}')
        time.sleep(0.5)

        new_ra, new_dec = self.get_equatorial()
        print(f'After sync:  RA={new_ra:.3f}h  DEC={new_dec:+.2f}')

        self._indi_set('ON_COORD_SET.SLEW', 'On')
        return True

    def sync_horizontal(self, sync_az: float, sync_alt: float) -> bool:
        """Sync mount to known Az/Alt coordinates (calibration).

        Args:
            sync_az: Known azimuth in degrees
            sync_alt: Known altitude in degrees

        Returns:
            True if sync succeeded
        """
        config = self.load_config()
        lat = config.get('lat')
        if lat is None:
            print('ERROR: Location not set.')
            print('  Run: mount-single set-location LAT LON')
            return False

        current_az, current_alt = self.get_horizontal()
        if current_az is None:
            print('ERROR: Cannot read position')
            return False

        print(f'Before sync: Az={current_az:.1f}  Alt={current_alt:+.1f}')
        print(f'Syncing to:  Az={sync_az:.1f}  Alt={sync_alt:+.1f}')

        result = self.azalt_to_radec(sync_az, sync_alt, lat)
        if result is None:
            print('ERROR: Cannot convert coordinates')
            return False

        sync_ra, sync_dec = result
        print(f'(Equivalent: RA={sync_ra:.2f}h  DEC={sync_dec:+.1f})')

        # Enable tracking and standard sync mode - required for sync on Star Adventurer GTi
        self._indi_set('TELESCOPE_TRACK_STATE.TRACK_ON', 'On')
        self._indi_set('ALIGNSYNCMODE.ALIGNSTANDARDSYNC', 'On')
        time.sleep(0.3)

        self._indi_set('ON_COORD_SET.SYNC', 'On')
        time.sleep(0.1)

        self._indi_set(f'EQUATORIAL_EOD_COORD.RA={sync_ra};DEC={sync_dec}')
        time.sleep(0.5)

        new_az, new_alt = self.get_horizontal()
        print(f'After sync:  Az={new_az:.1f}  Alt={new_alt:+.1f}')

        self._indi_set('ON_COORD_SET.SLEW', 'On')
        return True

    def show_status(self):
        """Show detailed mount status."""
        print('=== Mount Status ===\n')

        conn = self._indi_get('CONNECTION.CONNECT')
        print(f'Connected: {conn}')

        lat = self._indi_get('GEOGRAPHIC_COORD.LAT')
        lon = self._indi_get('GEOGRAPHIC_COORD.LONG')
        if lat and float(lat) > 1e-10:
            print(f'Location: Lat={float(lat):.4f} Lon={float(lon):.4f}')
        else:
            print('Location: NOT SET (required for Az/Alt GoTo)')

        az, alt = self.get_horizontal()
        if az:
            print(f'\nHorizontal: Az={az:.2f}  Alt={alt:+.2f}')

        ra, dec = self.get_equatorial()
        if ra:
            print(f'Equatorial: RA={ra:.4f}h  DEC={dec:+.2f}')

        ra_steps, dec_steps = self.get_steps()
        if ra_steps:
            print(f'Steps: RA={ra_steps:.0f}  DEC={dec_steps:.0f}')

        print(f'\nRA GoTo: {self._indi_get("RASTATUS.RAGoto")}')
        print(f'DEC GoTo: {self._indi_get("DESTATUS.DEGoto")}')

        coord_mode = 'SLEW' if self._indi_get('ON_COORD_SET.SLEW') == 'On' else \
                     'TRACK' if self._indi_get('ON_COORD_SET.TRACK') == 'On' else 'SYNC'
        print(f'Coord mode: {coord_mode}')


# Module-level convenience functions using default controller
_default_controller = None


def _get_controller() -> MountController:
    """Get or create default controller."""
    global _default_controller
    if _default_controller is None:
        _default_controller = MountController()
    return _default_controller


def get_horizontal() -> Tuple[Optional[float], Optional[float]]:
    """Get current Az/Alt position."""
    return _get_controller().get_horizontal()


def get_equatorial() -> Tuple[Optional[float], Optional[float]]:
    """Get current RA/DEC position."""
    return _get_controller().get_equatorial()


def goto_horizontal(target_az: float, target_alt: float) -> bool:
    """Slew to target Az/Alt position."""
    return _get_controller().goto_horizontal(target_az, target_alt)


def goto_equatorial(target_ra: float, target_dec: float) -> bool:
    """Slew to target RA/DEC position."""
    return _get_controller().goto_equatorial(target_ra, target_dec)


def sync_horizontal(sync_az: float, sync_alt: float) -> bool:
    """Sync mount to known Az/Alt coordinates."""
    return _get_controller().sync_horizontal(sync_az, sync_alt)


def sync_equatorial(sync_ra: float, sync_dec: float) -> bool:
    """Sync mount to known RA/DEC coordinates."""
    return _get_controller().sync_equatorial(sync_ra, sync_dec)


def stop_all():
    """Stop all motion immediately."""
    _get_controller().stop()


def setup_location(lat: Optional[float] = None, lon: Optional[float] = None) -> bool:
    """Set geographic coordinates."""
    return _get_controller().setup_location(lat, lon)


def load_config() -> dict:
    """Load mount configuration."""
    return _get_controller().load_config()
