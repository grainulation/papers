#!/usr/bin/env python3
"""Scan versioned and new release files for workstation paths and local build debris.

Scans binary bytes too. Historical scientific logs and sealed data are release
artifacts; ignored build caches are not. No path exemptions bypass this check.
"""
import argparse
import hashlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    'home-directory path': re.compile(rb'/(?:Users|home)/[A-Za-z0-9_.-]+/'),
    'private temporary path': re.compile(rb'/private/(?:var/folders|tmp)/'),
    'workstation package-manager path': re.compile(rb'/opt[/]homebrew/'),
    'private checkout reference': re.compile(rb'~[/]repo/'),
}
LOCAL_PARTS = {'.claude', '.codex', '.DS_Store', '__pycache__', '.venv', 'node_modules', '.pytest_cache', '.lake', 'target'}


def inspect(path, data):
    issues = []
    if LOCAL_PARTS.intersection(path.parts) or path.suffix in {'.pyc', '.pyo'}:
        issues.append('local configuration or generated build artifact')
    for label, pattern in PATTERNS.items():
        match = pattern.search(data)
        if match:
            line = data[:match.start()].count(b'\n') + 1
            issues.append(f'{label} (line {line})')
    return issues


def redaction_issues(root):
    issues = []
    row = re.compile(r'^\| `([^`]+)` \| `([0-9a-f]{64})` \| `([0-9a-f]{64})`', re.M)
    for doc in root.glob('papers/*/artifact/FROZEN_REDACTIONS.md'):
        seen = set()
        for name, original, published in row.findall(doc.read_text()):
            target = doc.parent / name
            label = str(doc.relative_to(root))
            if name in seen or not target.resolve().is_relative_to(doc.parent.resolve()):
                issues.append((label, f'duplicate or escaping redaction mapping: {name}'))
                continue
            seen.add(name)
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != published:
                issues.append((label, f'published redaction hash mismatch: {name}'))
    return issues


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    result = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
                            cwd=root, check=True, capture_output=True)
    count = 0
    bad = []
    for name in sorted(set(result.stdout.decode().split('\0')) - {''}):
        rel = Path(name)
        path = root / rel
        if path.is_symlink():
            bad.extend((name, reason) for reason in inspect(rel, str(path.readlink()).encode()))
            if path.readlink().is_absolute() or not path.resolve().is_relative_to(root) or not path.resolve().is_file():
                bad.append((name, 'symlink target must be relative, present, and inside the repository'))
            continue
        if not path.exists():
            continue  # tracked deletion in the working tree
        if not path.is_file():
            continue
        count += 1
        bad.extend((name, reason) for reason in inspect(rel, path.read_bytes()))
    bad.extend(redaction_issues(root))
    for name, reason in bad:
        print(f'error: {name}: {reason}')
    print(f'Public release scan: {count} files, {len(bad)} problems')
    return bool(bad)


if __name__ == '__main__':
    raise SystemExit(main())
