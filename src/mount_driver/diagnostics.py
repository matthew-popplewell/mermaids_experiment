"""Diagnostic tools for Star Adventurer GTi mount detection.

Checks USB connections and INDI server status for single or multiple mounts.

Example usage:
    from mount_driver.diagnostics import check_mount_hardware, check_indi_server

    hw_count = check_mount_hardware()
    mounts = check_indi_server()
"""

import os
import subprocess
from typing import List, Tuple


def check_mount_hardware() -> int:
    """Check if Star Adventurer GTi mount(s) are detected via USB.

    Returns:
        Number of likely mounts detected
    """
    print('=== USB Device Detection ===\n')

    # Look for both ttyUSB and ttyACM devices (GTi uses ttyACM via STM32)
    devices = []
    try:
        for d in os.listdir('/dev'):
            if 'ttyUSB' in d or 'ttyACM' in d:
                devices.append(f'/dev/{d}')
    except OSError:
        pass

    if not devices:
        print('ERROR: No USB serial devices found.')
        print('\nChecklist:')
        print('  - Is the mount powered on (12V)?')
        print('  - Is the USB cable connected?')
        print('  - Try a different USB port')
        return 0

    print(f'Found {len(devices)} USB serial device(s):\n')

    mount_count = 0
    for device in sorted(devices):
        try:
            result = subprocess.run(
                ['udevadm', 'info', '--query=property', f'--name={device}'],
                capture_output=True, text=True, timeout=5
            )

            vendor = ''
            model = ''
            serial = ''

            for line in result.stdout.split('\n'):
                if 'ID_VENDOR=' in line and 'FROM_DATABASE' not in line:
                    vendor = line.split('=')[1]
                if 'ID_MODEL=' in line and 'FROM_DATABASE' not in line:
                    model = line.split('=')[1]
                if 'ID_SERIAL_SHORT=' in line:
                    serial = line.split('=')[1]

            # Check if this looks like a Star Adventurer GTi
            is_mount = 'STM32' in model or 'Virtual' in model

            print(f'{device}:')
            print(f'  Vendor: {vendor}')
            print(f'  Model:  {model}')
            print(f'  Serial: {serial}')
            if is_mount:
                mount_count += 1
                print(f'  Status: Likely Star Adventurer GTi')
            print()
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
            print(f'{device}: Unable to query device info')
            print()

    return mount_count


def check_indi_server() -> List[Tuple[str, str]]:
    """Check if INDI server is running and mounts are connected.

    Returns:
        List of (device_name, port) tuples for connected mounts
    """
    print('=== INDI Server Status ===\n')

    # Check if indiserver process is running
    try:
        result = subprocess.run(['pgrep', '-a', 'indiserver'],
                                capture_output=True, text=True, timeout=5)
        if not result.stdout:
            print('INDI server: NOT RUNNING')
            print('  Start with: ./scripts/start_server.sh')
            return []

        print('INDI server: RUNNING')
        print(f'  {result.stdout.strip()}')
        print()
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        print('INDI server: Unable to check')
        return []

    # Check for connected mounts
    connected_mounts = []

    # Try "Star Adventurer GTi" (single mount mode)
    try:
        result = subprocess.run(
            ['indi_getprop', 'Star Adventurer GTi.CONNECTION.CONNECT'],
            capture_output=True, text=True, timeout=5
        )
        if 'On' in result.stdout:
            port_result = subprocess.run(
                ['indi_getprop', 'Star Adventurer GTi.DEVICE_PORT.PORT'],
                capture_output=True, text=True, timeout=5
            )
            port = port_result.stdout.strip().split('=')[1] if '=' in port_result.stdout else 'unknown'
            connected_mounts.append(('Star Adventurer GTi', port))
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        pass

    # Try "Mount 1", "Mount 2", etc. (multi-mount mode)
    for i in range(1, 11):
        device = f'Mount {i}'
        try:
            result = subprocess.run(
                ['indi_getprop', f'{device}.CONNECTION.CONNECT'],
                capture_output=True, text=True, timeout=3
            )
            if 'On' in result.stdout:
                port_result = subprocess.run(
                    ['indi_getprop', f'{device}.DEVICE_PORT.PORT'],
                    capture_output=True, text=True, timeout=3
                )
                port = port_result.stdout.strip().split('=')[1] if '=' in port_result.stdout else 'unknown'
                connected_mounts.append((device, port))
            elif result.returncode == 0:
                # Device exists but not connected
                connected_mounts.append((device, 'NOT CONNECTED'))
        except subprocess.TimeoutExpired:
            continue
        except subprocess.SubprocessError:
            break

    if connected_mounts:
        print('Connected mounts:')
        for name, port in connected_mounts:
            status = f'on {port}' if port != 'NOT CONNECTED' else 'NOT CONNECTED'
            print(f'  {name}: {status}')
    else:
        print('No mounts connected via INDI')
        print('  Wait a few seconds for auto-connect, or check USB connections')

    return connected_mounts


def run_diagnostics():
    """Run full mount diagnostics and print summary."""
    print('Star Adventurer GTi Mount Diagnostics\n')
    print('=' * 50)

    hw_count = check_mount_hardware()
    connected = check_indi_server()

    print('=' * 50)
    print('\nSummary:')
    print(f'  USB devices found: {hw_count}')
    print(f'  INDI mounts:       {len(connected)}')

    if hw_count > 0 and len(connected) > 0:
        if hw_count == 1:
            print('\nSingle mount ready. Run: mount-single')
        else:
            print(f'\nMultiple mounts ready. Run: mount-multi')
    elif hw_count > 0 and len(connected) == 0:
        print('\nStart INDI server:')
        if hw_count == 1:
            print('  ./scripts/start_server.sh')
        else:
            print(f'  ./scripts/start_server.sh {hw_count}')
    else:
        print('\nCheck mount power and USB connections.')
