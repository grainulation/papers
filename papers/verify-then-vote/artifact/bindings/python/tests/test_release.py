"""Release-facing acceptance checks; run against an installed wheel as well."""
import importlib.util
import struct
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gate_example():
    example = load('gate_example', ROOT / 'examples/verify_then_vote.py')
    example.run()
    example.run(accepted=False)


def test_reject_unknown_binary(tmp_path):
    mod = load('wheel_platform', ROOT / 'wheel_platform.py')
    binary = tmp_path / 'binary'
    binary.write_bytes(b'not an executable')
    with pytest.raises(ValueError, match='unsupported executable'):
        mod.binary_platform(binary)


def test_reject_wrong_architecture(tmp_path, monkeypatch):
    mod = load('wheel_platform', ROOT / 'wheel_platform.py')
    monkeypatch.setattr(mod.sys, 'platform', 'linux')
    monkeypatch.setattr(mod.platform, 'machine', lambda: 'x86_64')
    binary = tmp_path / 'binary'
    binary.write_bytes(b'\x7fELF\x02\x01' + b'\0' * 12 + struct.pack('<H', 183) + b'\0' * 12)
    with pytest.raises(ValueError, match='architecture'):
        mod.binary_platform(binary)


def test_linux_does_not_claim_manylinux(tmp_path, monkeypatch):
    mod = load('wheel_platform', ROOT / 'wheel_platform.py')
    monkeypatch.setattr(mod.sys, 'platform', 'linux')
    monkeypatch.setattr(mod.platform, 'machine', lambda: 'x86_64')
    binary = tmp_path / 'binary'
    binary.write_bytes(b'\x7fELF\x02\x01' + b'\0' * 12 + struct.pack('<H', 62) + b'\0' * 12)
    assert mod.binary_platform(binary) == 'linux_x86_64'
    monkeypatch.setenv('OVERTURN_WHEEL_PLAT', 'manylinux_2_17_x86_64')
    with pytest.raises(ValueError, match='overrides'):
        mod.validate_binary(binary)


def test_reject_wrong_reducer_constants(tmp_path, monkeypatch):
    from types import SimpleNamespace
    mod = load('wheel_platform', ROOT / 'wheel_platform.py')
    monkeypatch.setattr(mod, 'binary_platform', lambda p: 'linux_x86_64')
    monkeypatch.delenv('OVERTURN_WHEEL_PLAT', raising=False)
    monkeypatch.setattr(mod.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout='{"reducer_constants_id":"wrong"}'))
    (tmp_path / 'binary').write_bytes(b'fixture')
    with pytest.raises(ValueError, match='constants'):
        mod.validate_binary(tmp_path / 'binary')


def test_external_binary_paths_rejected_before_execution(tmp_path, monkeypatch):
    mod = load('wheel_platform', ROOT / 'wheel_platform.py')
    binary = tmp_path / 'binary'
    binary.write_bytes(b'\0/' + b'Users/person/source.rs\0')
    monkeypatch.setattr(mod.subprocess, 'run', lambda *a, **kw: pytest.fail('unsafe binary executed'))
    with pytest.raises(ValueError, match='workstation path'):
        mod.validate_binary(binary)


def test_compressed_wheel_paths_rejected(tmp_path):
    import zipfile
    mod = load('release_hygiene', ROOT / 'release_hygiene.py')
    wheel = tmp_path / 'example.whl'
    with zipfile.ZipFile(wheel, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('package/_bin/reducer', b'\0/' + b'home/builder/source.rs\0')
    with pytest.raises(ValueError, match='workstation path'):
        mod.check_wheel(wheel)
    with zipfile.ZipFile(wheel, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('package/_bin/reducer', b'\0/build/cargo/source.rs\0')
    assert mod.check_wheel(wheel) == wheel


def test_cargo_remaps_preserve_existing_flags(monkeypatch, tmp_path):
    mod = load('build_wheel', ROOT / 'scripts/build_wheel.py')
    monkeypatch.delenv('CARGO_ENCODED_RUSTFLAGS', raising=False)
    monkeypatch.setenv('RUSTFLAGS', '-C opt-level=2')
    env = mod.cargo_environment(tmp_path)
    flags = env['CARGO_ENCODED_RUSTFLAGS'].split('\x1f')
    assert flags[:2] == ['-C', 'opt-level=2']
    assert any(flag.endswith('=/build/cargo') for flag in flags)
    assert any(flag.endswith('=/build/artifact') for flag in flags)
    assert 'RUSTFLAGS' not in env


def test_standalone_sdist_cargo_guidance(tmp_path, monkeypatch, capsys):
    mod = load('build_wheel', ROOT / 'scripts/build_wheel.py')
    monkeypatch.setattr(mod, 'CRATE', tmp_path / 'missing-crate')
    monkeypatch.setattr(mod.sys, 'argv', ['build_wheel.py', '--cargo'])
    monkeypatch.setattr(mod.subprocess, 'run', lambda *a, **kw: pytest.fail('cargo should not run'))
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 2
    assert 'standalone sdist' in capsys.readouterr().err
