#!/usr/bin/env python3
"""
Diagnostic tool for Star Adventurer GTi mount detection.
Checks USB connections and INDI server status.
"""
import subprocess
import os


def check_mount_hardware():
    """Check if the Star Adventurer GTi mount is detected via USB."""
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
        return False

    print(f'Found devices: {devices}')

    # Get hardware details
    for device in devices:
        print(f'\n{device}:')
        result = subprocess.run(['udevadm', 'info', '--query=property', f'--name={device}'],
                                capture_output=True, text=True)

        for line in result.stdout.split('\n'):
            if any(k in line for k in ['ID_VENDOR=', 'ID_MODEL=', 'ID_SERIAL=']):
                print(f'  {line}')

    return True


def check_indi_server():
    """Check if INDI server is running and mount is connected."""
    print('\n=== INDI Server Status ===\n')

    # Check if indiserver process is running
    result = subprocess.run(['pgrep', '-a', 'indiserver'], capture_output=True, text=True)
    if not result.stdout:
        print('INDI server: NOT RUNNING')
        print('  Start with: ./start_server.sh')
        return False

    print(f'INDI server: RUNNING')
    print(f'  {result.stdout.strip()}')

    # Try to get mount connection status
    try:
        result = subprocess.run(
            ['indi_getprop', 'Star Adventurer GTi.CONNECTION.CONNECT'],
            capture_output=True, text=True, timeout=5
        )
        if 'On' in result.stdout:
            print('\nMount connection: CONNECTED')

            # Get device port
            result = subprocess.run(
                ['indi_getprop', 'Star Adventurer GTi.DEVICE_PORT.PORT'],
                capture_output=True, text=True, timeout=5
            )
            if '=' in result.stdout:
                port = result.stdout.strip().split('=')[1]
                print(f'  Port: {port}')
            return True
        else:
            print('\nMount connection: NOT CONNECTED')
            return False
    except subprocess.TimeoutExpired:
        print('\nMount connection: TIMEOUT (server may be starting)')
        return False
    except Exception as e:
        print(f'\nMount connection: ERROR ({e})')
        return False


def main():
    print('Star Adventurer GTi Mount Diagnostics\n')
    print('=' * 40)

    hw_ok = check_mount_hardware()
    indi_ok = check_indi_server()

    print('\n' + '=' * 40)
    print('\nSummary:')
    print(f'  USB Hardware: {"OK" if hw_ok else "PROBLEM"}')
    print(f'  INDI Server:  {"OK" if indi_ok else "PROBLEM"}')

    if hw_ok and indi_ok:
        print('\nMount is ready. Run: ./point_mount.py')
    elif hw_ok and not indi_ok:
        print('\nStart INDI server: ./start_server.sh')


if __name__ == '__main__':
    main()