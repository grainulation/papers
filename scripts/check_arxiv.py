#!/usr/bin/env python3
"""Inspect the generated arXiv archive and compile it outside the checkout."""
import argparse
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import tempfile

from check_public_release import inspect
from check_pdf import main as compare_pdf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paper', type=Path)
    args = parser.parse_args()
    paper = args.paper.resolve()
    with tempfile.TemporaryDirectory(prefix='paper-archive-check-') as directory:
        out = Path(directory)
        with tarfile.open(paper / 'tex/arxiv.tar.gz', 'r:gz') as archive:
            seen = set()
            for member in archive.getmembers():
                name = PurePosixPath(member.name)
                if (not member.isfile() or name.is_absolute() or '..' in name.parts
                        or member.name in seen or any(p.startswith('._') for p in name.parts)):
                    raise ValueError(f'unsafe or duplicate archive member: {member.name}')
                if member.pax_headers or member.uid or member.gid or member.uname or member.gname or member.mtime:
                    raise ValueError(f'local metadata in archive: {member.name}')
                data = archive.extractfile(member).read()
                problems = inspect(Path(member.name), data)
                if problems:
                    raise ValueError(f'non-public archive member {member.name}: {problems}')
                seen.add(member.name)
                dest = out.joinpath(*name.parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
        if 'main.tex' not in seen:
            raise ValueError('archive has no main.tex')
        documents = [('main', 'paper.pdf')]
        if 'supplement.tex' in seen:
            documents.append(('supplement', 'supplement.pdf'))
        for source, public in documents:
            subprocess.run(['tectonic', '--keep-logs', source + '.tex'], cwd=out, check=True)
            result = compare_pdf([str(paper / public), str(out / (source + '.pdf'))])
            if result:
                return result
        print(f'Clean arXiv archive: {len(seen)} files; {len(documents)} isolated builds match public PDFs')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
