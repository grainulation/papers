#!/usr/bin/env python3
"""Build a platform wheel with the overturn reducer binary bundled.

    python scripts/build_wheel.py                 # use overturn/target/release/overturn
    python scripts/build_wheel.py --bin PATH      # use a specific binary
    python scripts/build_wheel.py --cargo         # cargo build --release first
                                                  # (separate target dir)
    python scripts/build_wheel.py --pure          # no binary: py3-none-any wheel

The copied binary is removed from the source tree afterwards.
"""
from __future__ import annotations

import argparse
import os
import shutil
import shlex
import tempfile
import stat
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent           # bindings/python
REPO = HERE.parent.parent                                # repository root
CRATE = REPO / "overturn"
EXE = "overturn.exe" if sys.platform == "win32" else "overturn"
BINDIR = HERE / "src" / "overturn_arbiter" / "_bin"


def cargo_environment(target_dir):
    env = dict(os.environ, CARGO_TARGET_DIR=str(target_dir))
    flags = (env['CARGO_ENCODED_RUSTFLAGS'].split('\x1f') if env.get('CARGO_ENCODED_RUSTFLAGS')
             else shlex.split(env.get('RUSTFLAGS', '')))
    # Generic prefixes first: Rust selects the last matching remap.
    mappings = [(Path.home(), '/build/user'), (Path(tempfile.gettempdir()).resolve(), '/build/tmp'),
                (Path(env.get('CARGO_HOME', Path.home() / '.cargo')).resolve(), '/build/cargo'),
                (REPO.resolve(), '/build/artifact')]
    flags.extend('--remap-path-prefix=' + str(source) + '=' + destination for source, destination in mappings)
    env['CARGO_ENCODED_RUSTFLAGS'] = '\x1f'.join(flags)
    env.pop('RUSTFLAGS', None)
    return env


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bin", type=Path, help="reducer binary to bundle")
    ap.add_argument("--cargo", action="store_true", help="build the crate first (cargo build --release)")
    ap.add_argument("--target-dir", type=Path, default=HERE / "build" / "cargo-target",
                    help="CARGO_TARGET_DIR for --cargo (kept apart from overturn/target)")
    ap.add_argument("--pure", action="store_true", help="build a pure wheel without a binary")
    ap.add_argument("--outdir", type=Path, default=HERE / "dist")
    a = ap.parse_args()

    src = None
    if not a.pure:
        if a.cargo:
            if not (CRATE / "Cargo.toml").is_file():
                ap.error("--cargo requires the full papers repository with artifact/overturn/Cargo.toml. "
                         "A standalone sdist contains only the Python front end: use --pure and configure "
                         "OVERTURN_BIN, or --bin PATH with a separately built release reducer.")
            env = cargo_environment(a.target_dir)
            subprocess.run(["cargo", "build", "--release", "--locked", "--manifest-path", str(CRATE / "Cargo.toml")],
                           check=True, env=env)
            src = a.target_dir / "release" / EXE
        else:
            src = a.bin or Path(os.environ.get("OVERTURN_BIN", CRATE / "target" / "release" / EXE))
        if not src.is_file():
            print(f"no reducer binary at {src} (use --bin, --cargo or --pure)", file=sys.stderr)
            return 2

    dest = BINDIR / EXE
    if any((BINDIR / name).exists() for name in ("overturn", "overturn.exe")):
        raise RuntimeError("bundled source binary already exists; refusing to overwrite or delete it")
    if src is not None:
        sys.path.insert(0, str(HERE))
        from wheel_platform import validate_binary
        validate_binary(src)
    try:
        if src is not None:
            BINDIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            print(f"bundling {src} -> {dest}")
        subprocess.run([sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(a.outdir), str(HERE)],
                       check=True)
    finally:
        if src is not None and dest.exists():
            dest.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
