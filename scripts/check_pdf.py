#!/usr/bin/env python3
"""Reject a published PDF whose text differs from the freshly built manuscript.

Requires Poppler's pdftotext. Only whitespace is normalized; case, punctuation,
numbers, and page numbers remain significant. This complements, rather than
replaces, visual review of figures and page layout.
"""

import argparse
import subprocess
import sys
from pathlib import Path
from check_public_release import inspect


def extract_text(path):
    if not path.is_file():
        raise ValueError(f"missing PDF: {path}")
    try:
        result = subprocess.run(
            ["pdftotext", "-enc", "UTF-8", str(path.resolve()), "-"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise ValueError(f"could not extract PDF text from {path}: {exc}") from exc
    normalized = " ".join(result.stdout.split())
    if not normalized:
        raise ValueError(f"no extractable text in PDF: {path}")
    issues = inspect(path, normalized.encode("utf-8"))
    if issues:
        raise ValueError("PDF contains non-public paths: " + "; ".join(issues))
    return normalized


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("published", type=Path, help="committed public paper.pdf")
    parser.add_argument("built", type=Path, help="freshly built tex/main.pdf")
    args = parser.parse_args(argv)
    try:
        published = extract_text(args.published)
        built = extract_text(args.built)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if published != built:
        print(
            f"error: stale PDF: {args.published} differs in text from {args.built}; "
            "review the rebuilt manuscript and update the public PDF",
            file=sys.stderr,
        )
        return 1
    print(f"PDF text matches: {args.published}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
