#!/usr/bin/env python3
"""Fail if any uncompressed wheel member contains a workstation path."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from release_hygiene import check_wheel

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheels', nargs='+', type=Path)
    args = parser.parse_args()
    for wheel in args.wheels:
        check_wheel(wheel)
        print(f'PASS release contents: {wheel.name}')
