#!/usr/bin/env python3
"""Build a deterministic arXiv bundle from arxiv-files.txt, never a directory walk.

Add new source files explicitly to the manifest. Unlisted local files, filesystem
metadata, resource forks and symlinks cannot become archive members.
"""
import gzip
import io
from pathlib import Path, PurePosixPath
import tarfile
import tempfile


def source_files(root):
    manifest = root / "arxiv-files.txt"
    if manifest.is_symlink():
        raise ValueError("manifest must not be a symlink")
    names = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        name = line.strip()
        if not name or name.startswith("#"):
            continue
        parts = PurePosixPath(name).parts
        if (not parts or name != PurePosixPath(name).as_posix() or name.startswith("/")
                or "\\" in name or any(p in (".", "..") or p.startswith(".") for p in parts)):
            raise ValueError(f"unsafe archive member: {name!r}")
        if name in names:
            raise ValueError(f"duplicate archive member: {name}")
        current = root
        for part in parts:
            current = current / part
            if current.is_symlink():
                raise ValueError(f"symlink source refused: {name}")
        if not current.is_file():
            raise ValueError(f"missing or non-regular source: {name}")
        names.append(name)
    if not names:
        raise ValueError("empty source manifest")
    return sorted(names)


def build(root):
    root = Path(root).resolve()
    names = source_files(root)
    # Read all allowed bytes first, so any missing file fails before publication.
    contents = [(name, (root / name).read_bytes()) for name in names]
    target = root / "arxiv.tar.gz"
    if target.is_symlink():
        raise ValueError("archive output must not be a symlink")
    pending = None
    try:
        with tempfile.NamedTemporaryFile(dir=root, prefix="arxiv-", suffix=".tmp", delete=False) as raw:
            pending = Path(raw.name)
            with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                    for name, data in contents:
                        member = tarfile.TarInfo(name)
                        member.size = len(data)
                        member.mode = 0o644
                        member.uid = member.gid = member.mtime = 0
                        member.uname = member.gname = ""
                        member.pax_headers = {}
                        archive.addfile(member, io.BytesIO(data))
        pending.replace(target)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)
    return names


if __name__ == "__main__":
    members = build(Path(__file__).resolve().parent)
    print(f"Built arxiv.tar.gz: {len(members)} explicitly listed source files")
