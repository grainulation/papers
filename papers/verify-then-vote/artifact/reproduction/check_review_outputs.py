#!/usr/bin/env python3
"""Compare regenerated reviewer analyses with their published outputs."""
import argparse
import json
from pathlib import Path

PUBLISHED = Path(__file__).resolve().parent
PACKET_FILES = ('review_first_pass.jsonl', 'review_gold_second_pass.jsonl',
                'validation_channels.json')


def check_outputs(matched, audit, published=PUBLISHED):
    actual = json.loads((matched / 'results.json').read_text())
    expected = json.loads((published / 'matched_gate_results.json').read_text())
    # A source-built executable has a platform-specific identity. No other
    # receipt fields, including evaluator identity and freeze counts, may vary.
    for receipt in (actual, expected):
        identity = receipt.pop('binary_sha256')
        if not isinstance(identity, str) or len(identity) != 64 or any(
                c not in '0123456789abcdef' for c in identity):
            raise ValueError('invalid binary_sha256 in matched gate receipt')
    if json.dumps(actual, sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise ValueError('matched gate receipt differs from publication outside binary_sha256')
    for name in PACKET_FILES:
        if (audit / name).read_bytes() != (published / 'calibration_audit' / name).read_bytes():
            raise ValueError(f'calibration audit differs from publication: {name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--matched', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    args = parser.parse_args()
    check_outputs(args.matched, args.audit)
    print('PASS reviewer analyses match publication (only binary_sha256 may differ)')


if __name__ == '__main__':
    main()
