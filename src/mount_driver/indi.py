"""INDI protocol utilities for mount control.

Provides low-level communication with INDI server for telescope mount control.
Extracted common functions used by both single and multi-mount modules.
"""

import subprocess
from typing import Optional


# Default timeout for INDI commands
INDI_TIMEOUT = 5


def indi_get(prop: str, device: Optional[str] = None) -> Optional[str]:
    """Get INDI property value.

    Args:
        prop: Property path (e.g., 'CONNECTION.CONNECT')
        device: Device name (optional, can be included in prop)

    Returns:
        Property value as string, or None if not found
    """
    try:
        if device:
            full_prop = f'{device}.{prop}'
        else:
            full_prop = prop

        r = subprocess.run(
            ['indi_getprop', full_prop],
            capture_output=True,
            text=True,
            timeout=INDI_TIMEOUT
        )
        if '=' in r.stdout:
            return r.stdout.strip().split('=')[1]
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        pass
    return None


def indi_set(prop: str, value: Optional[str] = None, device: Optional[str] = None) -> bool:
    """Set INDI property value(s).

    Can be called as:
        indi_set('PROP.ELEMENT', 'value', device='Mount 1')  - Single property
        indi_set('PROP.A=1;B=2', device='Mount 1')           - Multiple properties

    Args:
        prop: Property path or full property=value string
        value: Value to set (optional if included in prop)
        device: Device name (optional, can be included in prop)

    Returns:
        True if command executed successfully
    """
    try:
        if device:
            if value is not None:
                cmd = f'{device}.{prop}={value}'
            else:
                cmd = f'{device}.{prop}'
        else:
            if value is not None:
                cmd = f'{prop}={value}'
            else:
                cmd = prop

        subprocess.run(
            ['indi_setprop', cmd],
            capture_output=True,
            timeout=INDI_TIMEOUT
        )
        return True
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return False


def check_indi_connection() -> bool:
    """Check if INDI server is running and accessible.

    Returns:
        True if INDI server is responding
    """
    try:
        result = subprocess.run(
            ['indi_getprop'],
            capture_output=True,
            text=True,
            timeout=INDI_TIMEOUT
        )
        return result.returncode == 0 or 'unable to connect' not in result.stderr.lower()
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return False


def get_device_property(device: str, prop: str) -> Optional[str]:
    """Get property value for a specific device.

    Args:
        device: INDI device name
        prop: Property path

    Returns:
        Property value or None
    """
    return indi_get(f'{device}.{prop}')


def set_device_property(device: str, prop: str, value: str) -> bool:
    """Set property value for a specific device.

    Args:
        device: INDI device name
        prop: Property path
        value: Value to set

    Returns:
        True if successful
    """
    return indi_set(prop, value, device=device)
