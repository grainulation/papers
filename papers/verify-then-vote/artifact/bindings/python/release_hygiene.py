"""Check the contents of generated release artifacts, including compressed members."""
import re
import zipfile
from pathlib import Path

PATTERNS = (
    re.compile(rb'/(?:Users|home)/[A-Za-z0-9_.-]+/'),
    re.compile(rb'/private/(?:var/folders|tmp)/'),
    re.compile(rb'/opt[/]homebrew/'),
    re.compile(rb'~[/]repo/'),
    re.compile(rb'[A-Za-z]:[\\/]Users[\\/][^\\/\x00\r\n]+[\\/]'),
)


def check_bytes(data, label):
    if any(pattern.search(data) for pattern in PATTERNS):
        raise ValueError(f'{label}: embedded workstation path; rebuild with release path remapping')


def check_wheel(path):
    with zipfile.ZipFile(path) as wheel:
        for member in wheel.infolist():
            check_bytes(member.filename.encode(), 'wheel member name')
            check_bytes(wheel.read(member), member.filename)
    return Path(path)
