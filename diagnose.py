#!/usr/bin/env python3
"""
Diagnostic tool for Star Adventurer GTi mount detection.
Checks USB connections and INDI server status for single or multiple mounts.
"""
import subprocess
import os


def check_mount_hardware():
    """Check if Star Adventurer GTi mount(s) are detected via USB."""
    print('=== USB Device Detection ===\n')

    # Look for both ttyUSB and ttyACM devices (GTi uses ttyACM via STM32)
    devices = []
    for d in os.listdir('/dev'):
        if 'ttyUSB' in d or 'ttyACM' in d:
            devices.append(f'/dev/{d}')

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
        result = subprocess.run(['udevadm', 'info', '--query=property', f'--name={device}'],
                                capture_output=True, text=True)

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

    return mount_count


def check_indi_server():
    """Check if INDI server is running and mounts are connected."""
    print('=== INDI Server Status ===\n')

    # Check if indiserver process is running
    result = subprocess.run(['pgrep', '-a', 'indiserver'], capture_output=True, text=True)
    if not result.stdout:
        print('INDI server: NOT RUNNING')
        print('  Start with: ./start_server.sh')
        return []

    print('INDI server: RUNNING')
    print(f'  {result.stdout.strip()}')
    print()

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
    except:
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
        except:
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


def main():
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
            print('\nSingle mount ready. Run: ./point_mount.py')
        else:
            print(f'\nMultiple mounts ready. Run: ./multi_mount.py')
    elif hw_count > 0 and len(connected) == 0:
        print('\nStart INDI server:')
        if hw_count == 1:
            print('  ./start_server.sh')
        else:
            print(f'  ./start_server.sh {hw_count}')
    else:
        print('\nCheck mount power and USB connections.')


if __name__ == '__main__':
    main()
