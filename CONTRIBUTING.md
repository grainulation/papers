# Contributing

The repository is preparing its first public release. After publication, changes to a paper are recorded as corrections; study inputs and protocol freezes remain preserved throughout preparation.

- **Errata.** Open an issue that names the paper, the section or table, the claim and the evidence. If a correction is needed, it is made in place, noted in the paper's README and recorded in [history.md](history.md).
- **Reproduction reports.** Reports of successful or failed reproductions are welcome as issues. Include the platform, the toolchain versions and the exact command.
- **Pull requests.** Fixes to build scripts, documentation and portability are welcome. Changes to a paper's text, data or frozen preregistration files are made by the authors only.

Frozen study inputs are verified by hash. Preserve original freeze maps and scientific data. If publication requires a path or metadata redaction, record the exact original and published hashes and the scope in the artifact's `FROZEN_REDACTIONS.md`; verify reconstruction against the original results. Never silently re-freeze edited files.

## Adding a paper

1. Choose a short, lowercase slug, such as `verify-then-vote`. Copy `templates/paper/` to `papers/<slug>/` and replace every `<<...>>` marker.
2. Put the manuscript source in `tex/`. `make` and `make arxiv` must work from that directory. Keep `tex/arxiv-files.txt` in sync with the source inputs; packaging includes only those explicit files and strips filesystem metadata. Commit the built PDF as `papers/<slug>/paper.pdf`. If the paper has separate supporting material, use `tex/supplement.tex` and publish `supplement.pdf` beside the paper; `make` must build both.
3. Put code, proofs and data in `artifact/`. Its `README.md` maps every result in the paper to a command and its expected output. `DATA_LICENSES.md` lists third-party data. Keep build products and caches out of git; the root `.gitignore` already covers `target/`, `.lake/` and evidence or judge caches.
   Include only public, self-contained artifacts. Use relative paths and environment variables for runtime configuration. Keep symlinks inside the repository. `scripts/check_public_release.py` checks release files, including binary bytes, for workstation paths and local configuration/build debris; frozen files have no path exemptions.
4. Add an entry to `catalogue.yaml`, an entry to `CONTENTS.md`, update the collection summary in `README.md` and a dated line to `history.md`.
5. If the artifact has its own checks, copy `templates/workflow.yml` to `.github/workflows/<slug>.yml`. Its path filter limits it to that paper. `papers.yml` builds every cataloged paper's PDF and arXiv bundle and runs `scripts/check_repo.py`, which fails when a paper is missing from the catalog, the map or the history, or lacks a required file.
6. Run `python3 scripts/check_repo.py`, `python3 scripts/check_public_release.py`, and the paper-specific artifact tests before committing. After building, run `python3 scripts/check_pdf.py papers/<slug>/paper.pdf papers/<slug>/tex/main.pdf`. CI compares normalized text so a stale public PDF fails; review figures and layout visually as well. Run `python3 scripts/check_arxiv.py papers/<slug>` to inspect and compile the generated archive outside the checkout, comparing both PDFs when a supplement is present.

Each paper is self-contained: it has its own toolchain pins, its own `artifact/` layout and its own licenses. Nothing outside `papers/<slug>/` (apart from the index files and its workflow) depends on it.

## Work in progress

Drafts are not kept in this repository, because its history is public. Work on a draft in a private repository with the same `papers/<slug>/` layout. When the paper is released, add it here in a single commit.
