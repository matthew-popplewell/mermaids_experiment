"""GPS Serial Module - Direct connection to GPS receivers.

Reads GPS coordinates directly from a USB GPS receiver via serial port.
No gpsd daemon required - connects directly to the GPS hardware.

Example usage:
    from mount_driver.gps import get_gps_location, gps_available, format_location

    if gps_available():
        location = get_gps_location(timeout=30)
        print(format_location(location))
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

import serial
import serial.tools.list_ports
import pynmea2


class GPSError(Exception):
    """Base exception for GPS errors."""
    pass


class GPSNotAvailable(GPSError):
    """GPS device not found or cannot connect."""
    pass


class NoFixError(GPSError):
    """GPS has no satellite fix."""
    pass


class FixTimeoutError(GPSError):
    """Timeout waiting for GPS fix."""
    pass


@dataclass
class GPSLocation:
    """GPS location data for mount positioning."""
    latitude: float
    longitude: float
    altitude: Optional[float] = None
    satellites: int = 0
    fix_type: str = '2D'  # '2D' or '3D'
    hdop: Optional[float] = None
    utc_time: Optional[datetime] = None


def find_gps_port() -> Optional[str]:
    """Auto-detect the GPS serial port.

    Returns:
        Port device path if found, None otherwise
    """
    ports = serial.tools.list_ports.comports()

    # Common identifiers for GPS receivers
    gps_identifiers = [
        'usbserial',
        'usbmodem',
        'CP210',      # Silicon Labs chip
        'FTDI',
        'GPS',
        'ACM',        # Linux USB ACM
        'Prolific',   # PL2303
    ]

    candidates = []
    for port in ports:
        port_info = f"{port.device} - {port.description} [{port.hwid}]"
        for identifier in gps_identifiers:
            if identifier.lower() in port_info.lower():
                candidates.append(port.device)
                break

    if candidates:
        return candidates[0]
    return None


def list_serial_ports() -> List[Dict]:
    """List all available serial ports.

    Returns:
        List of dicts with port info
    """
    ports = serial.tools.list_ports.comports()
    return [
        {
            'device': port.device,
            'description': port.description,
            'hwid': port.hwid,
            'manufacturer': port.manufacturer,
        }
        for port in ports
    ]


def gps_available(port: Optional[str] = None) -> bool:
    """Check if a GPS device is available.

    Args:
        port: Specific port to check, or None to auto-detect

    Returns:
        True if GPS device can be found
    """
    if port:
        try:
            ser = serial.Serial(port, 9600, timeout=1)
            ser.close()
            return True
        except serial.SerialException:
            return False
    else:
        return find_gps_port() is not None


class GPSReader:
    """Direct serial reader for GPS modules (e.g., Adafruit Ultimate GPS)."""

    def __init__(
        self,
        port: Optional[str] = None,
        baudrate: int = 9600,
        timeout: float = 2.0
    ):
        """Initialize GPS reader.

        Args:
            port: Serial port path. If None, auto-detects.
            baudrate: Serial baud rate (default 9600)
            timeout: Serial read timeout in seconds
        """
        self.port = port or find_gps_port()
        if self.port is None:
            raise GPSNotAvailable(
                "Could not auto-detect GPS port. "
                "Connect GPS receiver or specify port manually."
            )
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial: Optional[serial.Serial] = None

        # Current fix data
        self._latitude: Optional[float] = None
        self._longitude: Optional[float] = None
        self._altitude: Optional[float] = None
        self._fix_type: str = 'none'
        self._satellites: int = 0
        self._hdop: Optional[float] = None
        self._utc_time: Optional[datetime] = None

    def connect(self) -> None:
        """Open serial connection to GPS."""
        try:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout
            )
            self.serial.reset_input_buffer()
        except serial.SerialException as e:
            raise GPSNotAvailable(f"Cannot connect to GPS on {self.port}: {e}")

    def disconnect(self) -> None:
        """Close serial connection."""
        if self.serial and self.serial.is_open:
            self.serial.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False

    def _read_sentence(self) -> Optional[str]:
        """Read a single NMEA sentence from GPS."""
        if not self.serial:
            return None

        try:
            line = self.serial.readline().decode('ascii', errors='replace').strip()
            if line.startswith('$'):
                return line
        except (serial.SerialException, UnicodeDecodeError):
            pass
        return None

    def _parse_gga(self, msg: pynmea2.GGA) -> None:
        """Parse GGA sentence - essential fix data."""
        if msg.timestamp:
            today = datetime.now(timezone.utc).date()
            self._utc_time = datetime.combine(
                today,
                msg.timestamp,
                tzinfo=timezone.utc
            )

        if msg.latitude:
            self._latitude = msg.latitude
        if msg.longitude:
            self._longitude = msg.longitude
        if msg.altitude:
            self._altitude = msg.altitude
        if msg.num_sats:
            self._satellites = int(msg.num_sats)
        if msg.horizontal_dil:
            self._hdop = float(msg.horizontal_dil)

    def _parse_rmc(self, msg: pynmea2.RMC) -> None:
        """Parse RMC sentence - recommended minimum data."""
        if msg.datetime:
            self._utc_time = msg.datetime.replace(tzinfo=timezone.utc)

        if msg.latitude:
            self._latitude = msg.latitude
        if msg.longitude:
            self._longitude = msg.longitude

    def _parse_gsa(self, msg: pynmea2.GSA) -> None:
        """Parse GSA sentence - DOP and active satellites."""
        if msg.mode_fix_type:
            fix_types = {1: 'none', 2: '2D', 3: '3D'}
            self._fix_type = fix_types.get(int(msg.mode_fix_type), 'unknown')
        if msg.hdop:
            self._hdop = float(msg.hdop)

    def _parse_sentence(self, sentence: str) -> bool:
        """Parse an NMEA sentence and update GPS data."""
        try:
            msg = pynmea2.parse(sentence)

            if isinstance(msg, pynmea2.GGA):
                self._parse_gga(msg)
            elif isinstance(msg, pynmea2.RMC):
                self._parse_rmc(msg)
            elif isinstance(msg, pynmea2.GSA):
                self._parse_gsa(msg)

            return True
        except pynmea2.ParseError:
            return False

    def get_fix(
        self,
        timeout: float = 30.0,
        require_3d: bool = False,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> GPSLocation:
        """Read GPS data until we have a valid fix.

        Args:
            timeout: Maximum time to wait for fix in seconds
            require_3d: If True, wait for 3D fix (includes altitude)
            progress_callback: Optional function(satellites, status_message)

        Returns:
            GPSLocation with position data

        Raises:
            FixTimeoutError: Could not get fix within timeout
        """
        # Reset data
        self._latitude = None
        self._longitude = None
        self._altitude = None
        self._fix_type = 'none'
        self._satellites = 0
        self._hdop = None
        self._utc_time = None

        start_time = time.time()
        received = set()
        required = {'GGA', 'RMC', 'GSA'}

        while time.time() - start_time < timeout:
            sentence = self._read_sentence()
            if not sentence:
                continue

            if self._parse_sentence(sentence):
                if len(sentence) > 6 and sentence[3:6] in ('GGA', 'RMC', 'GSA'):
                    received.add(sentence[3:6])

            # Progress callback
            if progress_callback:
                if self._latitude is None:
                    progress_callback(self._satellites, "Searching...")
                else:
                    progress_callback(self._satellites, "Fix acquired")

            # Check if we have enough data
            have_required = required.issubset(received)
            have_position = self._latitude is not None and self._longitude is not None
            have_3d = self._fix_type == '3D' if require_3d else True

            if have_required and have_position and have_3d:
                return GPSLocation(
                    latitude=self._latitude,
                    longitude=self._longitude,
                    altitude=self._altitude,
                    satellites=self._satellites,
                    fix_type=self._fix_type,
                    hdop=self._hdop,
                    utc_time=self._utc_time,
                )

        raise FixTimeoutError(
            f"Could not get GPS fix within {timeout}s. "
            f"Try: --wait {int(timeout * 2)}"
        )


def get_gps_location(
    timeout: float = 30,
    port: Optional[str] = None,
    progress_callback: Optional[Callable[[int, str], None]] = None
) -> Dict:
    """Read GPS location from connected GPS receiver.

    This is a convenience function that returns a dict for easy use.

    Args:
        timeout: Maximum seconds to wait for a valid fix (default 30)
        port: Serial port (auto-detected if not specified)
        progress_callback: Optional function(satellites, status_message)

    Returns:
        dict with keys:
            lat: Latitude in degrees (positive=N, negative=S)
            lon: Longitude in degrees (positive=E, negative=W)
            alt: Altitude in meters (may be None)
            satellites: Number of satellites used
            fix_type: 2 for 2D fix, 3 for 3D fix
            accuracy: Horizontal accuracy estimate (may be None)

    Raises:
        GPSNotAvailable: GPS device not found or cannot connect
        FixTimeoutError: Could not get fix within timeout
    """
    with GPSReader(port=port) as reader:
        location = reader.get_fix(
            timeout=timeout,
            progress_callback=progress_callback
        )

    return {
        'lat': location.latitude,
        'lon': location.longitude,
        'alt': location.altitude,
        'satellites': location.satellites,
        'fix_type': 3 if location.fix_type == '3D' else 2,
        'accuracy': location.hdop * 5 if location.hdop else None,
    }


def format_location(location: Dict) -> str:
    """Format a location dict for display.

    Args:
        location: dict from get_gps_location()

    Returns:
        Formatted multi-line string for display
    """
    lat = location['lat']
    lon = location['lon']

    lat_dir = 'N' if lat >= 0 else 'S'
    lon_dir = 'E' if lon >= 0 else 'W'

    lines = [
        f"Latitude:   {abs(lat):.6f} {lat_dir}",
        f"Longitude:  {abs(lon):.6f} {lon_dir}",
        f"Satellites: {location['satellites']}",
        f"Fix type:   {'3D' if location['fix_type'] == 3 else '2D'}"
    ]

    if location.get('alt') is not None:
        lines.insert(2, f"Altitude:   {location['alt']:.1f} m")

    if location.get('accuracy') is not None:
        lines.append(f"Accuracy:   ~{location['accuracy']:.1f} m")

    return '\n'.join(lines)
