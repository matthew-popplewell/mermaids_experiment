"""Multi-mount control for Star Adventurer GTi arrays.

Controls multiple co-located mounts to point at the same Az/El coordinates.
All mounts share the same geographic location.

Example usage:
    from mount_driver.multi_mount import MultiMountController

    controller = MultiMountController()
    controller.setup_location(39.917, -105.004)
    controller.goto_all(90, 45)  # All mounts to Az=90, El=45
"""

import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from mount_driver.indi import indi_get, indi_set, check_indi_connection


# Configuration file location
CONFIG_DIR = Path(__file__).parent
CONFIG_FILE = CONFIG_DIR / '.multi_mount_config.json'

# Mount naming convention used by INDI
MOUNT_PREFIX = 'Mount '

# Mount constants
STEPS_PER_360_RA = 3628800.0
STEPS_PER_360_DEC = 2903040.0
GOTO_TIMEOUT = 300


@dataclass
class MountInfo:
    """Information about a discovered mount."""
    id: int
    device: str
    connected: bool
    port: Optional[str] = None
    az: Optional[float] = None
    alt: Optional[float] = None
    ra: Optional[float] = None
    dec: Optional[float] = None


class MultiMountController:
    """Controller for multiple Star Adventurer GTi mounts."""

    def __init__(self):
        """Initialize multi-mount controller."""
        self._config_file = CONFIG_FILE

    def discover_mounts(self) -> List[MountInfo]:
        """Discover all connected mounts via INDI.

        Returns:
            List of MountInfo for discovered mounts
        """
        mounts = []

        for i in range(1, 11):
            device = f'{MOUNT_PREFIX}{i}'
            conn = indi_get(f'{device}.CONNECTION.CONNECT')
            if conn is not None:
                mounts.append(MountInfo(
                    id=i,
                    device=device,
                    connected=conn == 'On'
                ))

        return mounts

    def get_mount_status(self, mount: MountInfo) -> MountInfo:
        """Get detailed status for a single mount.

        Args:
            mount: MountInfo to update

        Returns:
            Updated MountInfo with position data
        """
        device = mount.device

        port = indi_get(f'{device}.DEVICE_PORT.PORT')
        az = indi_get(f'{device}.HORIZONTAL_COORD.AZ')
        alt = indi_get(f'{device}.HORIZONTAL_COORD.ALT')
        ra = indi_get(f'{device}.EQUATORIAL_EOD_COORD.RA')
        dec = indi_get(f'{device}.EQUATORIAL_EOD_COORD.DEC')

        return MountInfo(
            id=mount.id,
            device=device,
            connected=mount.connected,
            port=port,
            az=float(az) if az else None,
            alt=float(alt) if alt else None,
            ra=float(ra) if ra else None,
            dec=float(dec) if dec else None
        )

    def load_config(self) -> dict:
        """Load configuration."""
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
        """Set geographic coordinates for all mounts.

        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees

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

        mounts = self.discover_mounts()
        for mount in mounts:
            indi_set(f'{mount.device}.GEOGRAPHIC_COORD.LAT={lat};LONG={lon}')

        return True

    def get_lst(self, device: str) -> Optional[float]:
        """Get local sidereal time from a mount."""
        lst = indi_get(f'{device}.TIME_LST.LST')
        if lst:
            return float(lst)
        return None

    def azalt_to_radec(self, az: float, alt: float, lat: float, device: str) -> Optional[Tuple[float, float]]:
        """Convert Az/Alt to RA/DEC using LST from specified mount.

        Args:
            az: Azimuth in degrees (0=North, 90=East, 180=South, 270=West)
            alt: Altitude in degrees
            lat: Observer latitude in degrees
            device: INDI device name for LST

        Returns:
            (ra_hours, dec_degrees) or None
        """
        lst = self.get_lst(device)
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

    def radec_to_azalt(self, ra_hours: float, dec_deg: float, lat: float, device: str) -> Optional[Tuple[float, float]]:
        """Convert RA/DEC to Az/Alt using LST from specified mount.

        Args:
            ra_hours: Right Ascension in hours (0-24)
            dec_deg: Declination in degrees (-90 to 90)
            lat: Observer latitude in degrees
            device: INDI device name for LST

        Returns:
            (az_degrees, alt_degrees) or None - Az is 0=North, 90=East
        """
        lst = self.get_lst(device)
        if lst is None:
            return None

        # Hour angle = LST - RA
        ha_hours = lst - ra_hours
        while ha_hours < -12:
            ha_hours += 24
        while ha_hours > 12:
            ha_hours -= 24

        ha_rad = math.radians(ha_hours * 15.0)
        dec_rad = math.radians(dec_deg)
        lat_rad = math.radians(lat)

        # Calculate altitude
        sin_alt = math.sin(dec_rad) * math.sin(lat_rad) + \
                  math.cos(dec_rad) * math.cos(lat_rad) * math.cos(ha_rad)
        alt_rad = math.asin(max(-1, min(1, sin_alt)))

        # Calculate azimuth
        cos_alt = math.cos(alt_rad)
        if abs(cos_alt) < 1e-10:
            az_rad = 0
        else:
            sin_az = -math.sin(ha_rad) * math.cos(dec_rad) / cos_alt
            cos_az = (math.sin(dec_rad) - math.sin(lat_rad) * math.sin(alt_rad)) / \
                     (math.cos(lat_rad) * cos_alt)
            az_rad = math.atan2(sin_az, cos_az)

        az_deg = math.degrees(az_rad)
        while az_deg < 0:
            az_deg += 360
        while az_deg >= 360:
            az_deg -= 360

        return az_deg, math.degrees(alt_rad)

    def _wait_for_mount_goto(self, device: str, timeout: float = GOTO_TIMEOUT) -> bool:
        """Wait for a single mount's GoTo to complete."""
        start = time.time()
        last_ra_steps = None
        last_dec_steps = None
        stable_count = 0
        moving_detected = False

        while time.time() - start < timeout:
            ra_steps = indi_get(f'{device}.CURRENTSTEPPERS.RAStepsCurrent')
            dec_steps = indi_get(f'{device}.CURRENTSTEPPERS.DEStepsCurrent')

            if ra_steps and dec_steps:
                ra_steps = float(ra_steps)
                dec_steps = float(dec_steps)

                if last_ra_steps is not None:
                    ra_delta = abs(ra_steps - last_ra_steps)
                    dec_delta = abs(dec_steps - last_dec_steps)

                    if ra_delta > 100 or dec_delta > 100:
                        moving_detected = True
                        stable_count = 0
                    else:
                        stable_count += 1
                        if moving_detected and stable_count >= 4:
                            return True
                        elif not moving_detected and stable_count >= 6:
                            return False

                last_ra_steps = ra_steps
                last_dec_steps = dec_steps

            time.sleep(0.5)

        return False

    def _goto_mount(self, device: str, target_ra: float, target_dec: float) -> bool:
        """Send GoTo command to a single mount."""
        indi_set(f'{device}.ON_COORD_SET.SLEW', 'On')
        time.sleep(0.1)
        indi_set(f'{device}.EQUATORIAL_EOD_COORD.RA={target_ra};DEC={target_dec}')
        return self._wait_for_mount_goto(device)

    def _sync_mount(self, device: str, sync_ra: float, sync_dec: float) -> bool:
        """Sync a single mount to coordinates."""
        # Read position before sync
        before_ra = indi_get(f'{device}.EQUATORIAL_EOD_COORD.RA')
        before_dec = indi_get(f'{device}.EQUATORIAL_EOD_COORD.DEC')

        # Enable tracking and standard sync mode - required for sync on Star Adventurer GTi
        indi_set(f'{device}.TELESCOPE_TRACK_STATE.TRACK_ON', 'On')
        indi_set(f'{device}.ALIGNSYNCMODE.ALIGNSTANDARDSYNC', 'On')
        time.sleep(0.3)

        indi_set(f'{device}.ON_COORD_SET.SYNC', 'On')
        time.sleep(0.1)
        indi_set(f'{device}.EQUATORIAL_EOD_COORD.RA={sync_ra};DEC={sync_dec}')
        time.sleep(0.5)

        # Read position after sync to verify
        after_ra = indi_get(f'{device}.EQUATORIAL_EOD_COORD.RA')
        after_dec = indi_get(f'{device}.EQUATORIAL_EOD_COORD.DEC')

        # Calculate how much offset was actually applied
        if before_ra and after_ra:
            ra_change = float(after_ra) - float(before_ra)
            dec_change = float(after_dec) - float(before_dec)
            expected_ra_change = sync_ra - float(before_ra)
            expected_dec_change = sync_dec - float(before_dec)
            print(f'      [Sync debug] RA change: expected {expected_ra_change:+.4f}h, actual {ra_change:+.4f}h')
            print(f'      [Sync debug] Dec change: expected {expected_dec_change:+.2f}°, actual {dec_change:+.2f}°')

        indi_set(f'{device}.ON_COORD_SET.SLEW', 'On')
        return True

    def stop_mount(self, device: str):
        """Stop a single mount."""
        indi_set(f'{device}.TELESCOPE_ABORT_MOTION.ABORT', 'On')

    def goto_all(self, target_az: float, target_alt: float,
                 mount_filter: Optional[int] = None) -> bool:
        """Command all mounts (or specific mount) to Az/El coordinates.

        Args:
            target_az: Target azimuth in degrees
            target_alt: Target altitude in degrees
            mount_filter: Specific mount ID to control (None for all)

        Returns:
            True if all mounts reached target
        """
        config = self.load_config()
        lat = config.get('lat')
        if lat is None:
            print('ERROR: Location not set. Run: mount-multi set-location LAT LON')
            return False

        mounts = self.discover_mounts()
        if not mounts:
            print('ERROR: No mounts discovered. Is INDI server running?')
            return False

        if mount_filter is not None:
            mounts = [m for m in mounts if m.id == mount_filter]
            if not mounts:
                print(f'ERROR: Mount {mount_filter} not found')
                return False

        first_device = mounts[0].device
        result = self.azalt_to_radec(target_az, target_alt, lat, first_device)
        if result is None:
            print('ERROR: Cannot convert coordinates')
            return False

        target_ra, target_dec = result

        print(f'Target: Az={target_az:.1f}  Alt={target_alt:+.1f}')
        print(f'        RA={target_ra:.4f}h  DEC={target_dec:+.2f}')
        print()

        print(f'Slewing {len(mounts)} mount(s)...')

        results = {}
        with ThreadPoolExecutor(max_workers=len(mounts)) as executor:
            futures = {
                executor.submit(self._goto_mount, m.device, target_ra, target_dec): m
                for m in mounts
            }

            for future in as_completed(futures):
                mount = futures[future]
                try:
                    success = future.result()
                    results[mount.id] = success
                    status = 'Done' if success else 'FAILED'

                    # Get actual position
                    az = indi_get(f'{mount.device}.HORIZONTAL_COORD.AZ')
                    alt = indi_get(f'{mount.device}.HORIZONTAL_COORD.ALT')
                    ra = indi_get(f'{mount.device}.EQUATORIAL_EOD_COORD.RA')
                    dec = indi_get(f'{mount.device}.EQUATORIAL_EOD_COORD.DEC')

                    if az and alt:
                        actual_az = float(az)
                        actual_alt = float(alt)
                        # Calculate error
                        az_err = actual_az - target_az
                        if az_err > 180:
                            az_err -= 360
                        elif az_err < -180:
                            az_err += 360
                        alt_err = actual_alt - target_alt

                        print(f'  Mount {mount.id}: {status}')
                        print(f'    Actual:  Az={actual_az:.1f}  Alt={actual_alt:+.1f}')
                        print(f'    Error:   Az={az_err:+.2f}  Alt={alt_err:+.2f}')
                        if ra and dec:
                            print(f'    RA/Dec:  RA={float(ra):.4f}h  Dec={float(dec):+.2f}')
                    else:
                        print(f'  Mount {mount.id}: {status}')
                except Exception as e:
                    results[mount.id] = False
                    print(f'  Mount {mount.id}: ERROR - {e}')

        return all(results.values())

    def sync_all(self, sync_az: float, sync_alt: float,
                 mount_filter: Optional[int] = None) -> bool:
        """Sync all mounts (or specific mount) to Az/El coordinates.

        Args:
            sync_az: Known azimuth in degrees
            sync_alt: Known altitude in degrees
            mount_filter: Specific mount ID to sync (None for all)

        Returns:
            True if all syncs succeeded
        """
        config = self.load_config()
        lat = config.get('lat')
        if lat is None:
            print('ERROR: Location not set. Run: mount-multi set-location LAT LON')
            return False

        mounts = self.discover_mounts()
        if not mounts:
            print('ERROR: No mounts discovered')
            return False

        if mount_filter is not None:
            mounts = [m for m in mounts if m.id == mount_filter]
            if not mounts:
                print(f'ERROR: Mount {mount_filter} not found')
                return False

        print(f'Syncing {len(mounts)} mount(s) to Az={sync_az:.1f}  Alt={sync_alt:+.1f}')
        print()
        print('NOTE: If using phone compass, values are MAGNETIC. For true north,')
        print('      subtract local magnetic declination (~7° in Colorado).')
        print()

        for mount in mounts:
            device = mount.device

            # Read position before sync
            before_az = indi_get(f'{device}.HORIZONTAL_COORD.AZ')
            before_alt = indi_get(f'{device}.HORIZONTAL_COORD.ALT')
            before_ra = indi_get(f'{device}.EQUATORIAL_EOD_COORD.RA')
            before_dec = indi_get(f'{device}.EQUATORIAL_EOD_COORD.DEC')

            result = self.azalt_to_radec(sync_az, sync_alt, lat, device)
            if result is None:
                print(f'  Mount {mount.id}: ERROR - Cannot convert coordinates')
                continue

            sync_ra, sync_dec = result
            print(f'  Mount {mount.id}:')
            if before_az and before_alt:
                print(f'    Before: Az={float(before_az):.1f}  Alt={float(before_alt):+.1f}')
                print(f'            RA={float(before_ra):.4f}h  Dec={float(before_dec):+.2f}')
            print(f'    Sync to: Az={sync_az:.1f}  Alt={sync_alt:+.1f}')
            print(f'             RA={sync_ra:.4f}h  Dec={sync_dec:+.2f}')

            self._sync_mount(device, sync_ra, sync_dec)

            # Wait for HORIZONTAL_COORD to update after sync
            time.sleep(0.5)

            # Read position after sync
            az = indi_get(f'{device}.HORIZONTAL_COORD.AZ')
            alt = indi_get(f'{device}.HORIZONTAL_COORD.ALT')
            ra = indi_get(f'{device}.EQUATORIAL_EOD_COORD.RA')
            dec = indi_get(f'{device}.EQUATORIAL_EOD_COORD.DEC')

            if az and alt:
                actual_az = float(az)
                actual_alt = float(alt)
                az_err = actual_az - sync_az
                if az_err > 180:
                    az_err -= 360
                elif az_err < -180:
                    az_err += 360
                alt_err = actual_alt - sync_alt

                print(f'    After:  Az={actual_az:.1f}  Alt={actual_alt:+.1f}')
                print(f'            RA={float(ra):.4f}h  Dec={float(dec):+.2f}')
                print(f'    Error:  Az={az_err:+.2f}  Alt={alt_err:+.2f}')

                if abs(az_err) > 1 or abs(alt_err) > 1:
                    print(f'    *** WARNING: Sync may not have taken effect! ***')
            else:
                print(f'    After: (unable to read position)')
            print()

        return True

    def stop_all(self):
        """Emergency stop all mounts."""
        mounts = self.discover_mounts()
        for mount in mounts:
            self.stop_mount(mount.device)
        print(f'Stopped {len(mounts)} mount(s)')

    def show_status(self):
        """Show status of all mounts."""
        mounts = self.discover_mounts()

        if not mounts:
            print('No mounts discovered. Is INDI server running?')
            print('  Start with: ./scripts/start_server.sh')
            return

        config = self.load_config()
        lat = config.get('lat')
        lon = config.get('lon')

        print('=== Multi-Mount Status ===\n')

        if lat:
            print(f'Location: Lat={lat:.4f}  Lon={lon:.4f}')
        else:
            print('Location: NOT SET')

        print(f'\nMounts discovered: {len(mounts)}\n')

        for mount in mounts:
            status = self.get_mount_status(mount)
            conn_str = 'CONNECTED' if status.connected else 'disconnected'

            print(f'Mount {status.id}: {conn_str}')
            if status.port:
                print(f'  Port: {status.port}')
            if status.az is not None:
                print(f'  Position: Az={status.az:.1f}  Alt={status.alt:+.1f}')
                print(f'            RA={status.ra:.3f}h  DEC={status.dec:+.1f}')
            print()

    def get_available_ports(self) -> List[str]:
        """Get list of available ttyACM ports (Star Adventurer GTi mounts)."""
        ports = []
        for i in range(10):
            port = f'/dev/ttyACM{i}'
            if os.path.exists(port):
                ports.append(port)
        return ports

    def auto_connect(self) -> bool:
        """Automatically assign ports and connect all mounts.

        Returns:
            True if all mounts connected
        """
        mounts = self.discover_mounts()

        if not mounts:
            print('No mounts discovered. Is INDI server running?')
            return False

        ports = self.get_available_ports()
        if not ports:
            print('No USB devices found at /dev/ttyACM*')
            return False

        if len(ports) < len(mounts):
            print(f'Warning: Found {len(ports)} ports but {len(mounts)} mount instances')

        print(f'Auto-connecting {len(mounts)} mount(s) to {len(ports)} port(s)...')

        for i, mount in enumerate(mounts):
            if i >= len(ports):
                print(f'  Mount {mount.id}: No available port')
                continue

            device = mount.device
            port = ports[i]

            indi_set(f'{device}.DEVICE_PORT.PORT', port)
            time.sleep(0.3)

            indi_set(f'{device}.CONNECTION.CONNECT', 'On')
            time.sleep(2)

            conn = indi_get(f'{device}.CONNECTION.CONNECT')
            if conn == 'On':
                print(f'  Mount {mount.id}: Connected on {port}')
            else:
                print(f'  Mount {mount.id}: FAILED to connect on {port}')

        self.setup_location()
        return True


# Module-level convenience functions
_default_controller = None


def _get_controller() -> MultiMountController:
    """Get or create default controller."""
    global _default_controller
    if _default_controller is None:
        _default_controller = MultiMountController()
    return _default_controller


def discover_mounts() -> List[MountInfo]:
    """Discover all connected mounts via INDI."""
    return _get_controller().discover_mounts()


def goto_all_mounts(target_az: float, target_alt: float,
                    mount_filter: Optional[int] = None) -> bool:
    """Command all mounts to Az/El coordinates."""
    return _get_controller().goto_all(target_az, target_alt, mount_filter)


def sync_all_mounts(sync_az: float, sync_alt: float,
                    mount_filter: Optional[int] = None) -> bool:
    """Sync all mounts to Az/El coordinates."""
    return _get_controller().sync_all(sync_az, sync_alt, mount_filter)


def stop_all_mounts():
    """Emergency stop all mounts."""
    _get_controller().stop_all()
