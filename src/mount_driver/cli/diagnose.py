"""CLI for mount diagnostics.

Usage:
    mount-diagnose              # Run full diagnostics
"""

import argparse
import sys

from mount_driver.diagnostics import run_diagnostics


def main():
    """Entry point for mount-diagnose command."""
    parser = argparse.ArgumentParser(
        description='Diagnostic tool for Star Adventurer GTi mount detection',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Checks:
  - USB device detection (ttyUSB, ttyACM)
  - INDI server status
  - Mount connections

Example:
  mount-diagnose
""",
    )

    parser.parse_args()
    run_diagnostics()
    return 0


if __name__ == '__main__':
    sys.exit(main())
