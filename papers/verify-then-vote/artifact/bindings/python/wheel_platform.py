"""Conservative native executable checks for bundled wheels (no ABI promises)."""
import json
import os
import platform
import re
import struct
import subprocess
import sys
from pathlib import Path


def binary_platform(binary):
    data = Path(binary).read_bytes()[:32]
    host = platform.machine().lower()
    host = {'amd64': 'x86_64', 'aarch64': 'arm64'}.get(host, host)
    if data[:4] == b'\xcf\xfa\xed\xfe':
        arch = {0x01000007: 'x86_64', 0x0100000c: 'arm64'}.get(struct.unpack('<I', data[4:8])[0])
        if sys.platform != 'darwin' or arch != host:
            raise ValueError('Mach-O binary architecture does not match the native build host')
        out = subprocess.run(['otool', '-l', str(binary)], capture_output=True, text=True, check=True).stdout
        m = re.search(r'LC_BUILD_VERSION.*?minos (\d+)\.(\d+)', out, re.S)
        if not m:
            raise ValueError('cannot determine Mach-O minimum OS version')
        major, minor = map(int, m.groups())
        return f'macosx_{major}_{minor if major < 11 else 0}_{arch}'
    if data[:4] == b'\x7fELF' and len(data) >= 20 and data[4:6] == b'\x02\x01':
        arch = {62: 'x86_64', 183: 'arm64'}.get(struct.unpack('<H', data[18:20])[0])
        if not sys.platform.startswith('linux') or arch != host:
            raise ValueError('ELF binary architecture does not match the native build host')
        # A host Python manylinux tag says nothing about this executable's glibc ABI.
        return 'linux_' + ('aarch64' if arch == 'arm64' else arch)
    raise ValueError('unsupported executable; build a native 64-bit macOS or Linux reducer')


def validate_binary(binary):
    import importlib.util
    spec = importlib.util.spec_from_file_location("release_hygiene", Path(__file__).with_name("release_hygiene.py"))
    hygiene = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hygiene)
    hygiene.check_bytes(Path(binary).read_bytes(), "reducer binary")
    tag = binary_platform(binary)
    override = os.environ.get('OVERTURN_WHEEL_PLAT')
    if override and override != tag:
        raise ValueError('platform overrides cannot assert unverified architecture or ABI compatibility')
    source = (Path(__file__).parent / 'src/overturn_arbiter/api.py').read_text()
    expected = re.search(r'REDUCER_CONSTANTS_ID = "([^"]+)"', source).group(1)
    result = subprocess.run([str(Path(binary).resolve()), '--version'], capture_output=True,
                            text=True, check=True, timeout=15)
    if json.loads(result.stdout).get('reducer_constants_id') != expected:
        raise ValueError('reducer constants do not match this Python package')
    return tag
