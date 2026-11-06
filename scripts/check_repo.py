#!/usr/bin/env python3
"""Check that the collection is consistent: every paper directory is catalogued,
every catalogue entry points at files that exist, and each paper has the files
the repository layout promises. Prints the catalogued slugs as JSON with --slugs.

The same script runs in the drafts repository with --drafts, which requires only
the source skeleton (no built PDF, map or history entry)."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ["README.md", "paper.pdf", "tex/Makefile", "tex/main.tex", "artifact/README.md"]
REQUIRED_DRAFT = ["README.md", "tex/Makefile", "tex/main.tex", "artifact/README.md"]


def load_catalogue():
    # The catalogue is plain YAML; read the fields we need without a YAML dependency.
    entries, cur = [], None
    for line in (ROOT / "catalogue.yaml").read_text().splitlines():
        m = re.match(r"^\s*-\s+slug:\s*(\S+)", line)
        if m:
            cur = {"slug": m.group(1)}
            entries.append(cur)
            continue
        m = re.match(r"^\s+(pdf|source|artifact|title|date|status):\s*(.+)$", line)
        if m and cur is not None:
            cur[m.group(1)] = m.group(2).strip().strip('"')
    return entries


def main(argv):
    entries = load_catalogue()
    if "--slugs" in argv:
        print(json.dumps([e["slug"] for e in entries]))
        return 0
    drafts = "--drafts" in argv
    errors = []
    slugs = [e["slug"] for e in entries]
    if len(set(slugs)) != len(slugs):
        errors.append("duplicate slugs in catalogue.yaml")
    pdir = ROOT / "papers"
    dirs = sorted(p.name for p in pdir.iterdir() if p.is_dir()) if pdir.exists() else []
    for d in dirs:
        if d not in slugs:
            errors.append(f"papers/{d} is not in catalogue.yaml")
    contents = "" if drafts else (ROOT / "CONTENTS.md").read_text()
    history = "" if drafts else (ROOT / "history.md").read_text()
    for e in entries:
        base = ROOT / "papers" / e["slug"]
        for k in (("source", "artifact") if drafts else ("pdf", "source", "artifact")):
            if k in e and not (ROOT / e[k]).exists():
                errors.append(f"{e['slug']}: {k} path {e[k]} does not exist")
        for f in (REQUIRED_DRAFT if drafts else REQUIRED):
            if not (base / f).exists():
                errors.append(f"{e['slug']}: missing {f}")
        if not drafts and (base / "tex/supplement.tex").exists() and not (base / "supplement.pdf").is_file():
            errors.append(f"{e['slug']}: supplementary source has no public supplement.pdf")
        if drafts:
            continue
        if (base / "README.md").exists() and "## Citation" not in (base / "README.md").read_text():
            errors.append(f"{e['slug']}: README.md has no Citation section")
        if f"papers/{e['slug']}/" not in contents:
            errors.append(f"{e['slug']}: not linked from CONTENTS.md")
        if f"papers/{e['slug']}/" not in history:
            errors.append(f"{e['slug']}: not recorded in history.md")
    for e in errors:
        print("error:", e)
    print(f"{len(entries)} papers checked, {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
