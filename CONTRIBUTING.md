# Maintaining the collection

The repository is preparing its first public release. After publication, changes to a paper are recorded as corrections; study inputs and protocol freezes remain preserved throughout preparation.

- **Errata.** Authors make scientific revisions in place, note them in the paper's README and record them in [history.md](history.md), identifying the paper, section or table, claim and supporting evidence.
- **Reproduction fixes.** Maintenance changes to build, portability or documentation should record the platform, toolchain versions, exact command and observed result.
- **Review.** Repository owners can inspect proposed maintenance branches through GitHub's compare view and use their maintainer workflow to integrate them. A compare branch is not a submitted pull request. Changes to a paper's text, data or frozen preregistration files are made by the authors only.

Public Issues, Discussions and Pull Requests are disabled. There is currently
no general public submission channel. This collection's read-only publication
profile is deliberate; do not change frozen scientific inputs to fit an
application contribution process. Sensitive execution vulnerabilities use the
verified private route in [SECURITY.md](SECURITY.md).

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

## CI bootstrap inputs

Workflow actions use immutable commit references, with their existing resolved
versions recorded in comments. The document build keeps Tectonic 0.17.0; the
proof job installs Elan 4.4.0 directly instead of using a shell bootstrap that
selects the latest release. Both executable archives are checked against the
SHA-256 published in their official GitHub release asset metadata before
extraction or execution:

- [Tectonic 0.17.0 release](https://github.com/tectonic-typesetting/tectonic/releases/tag/tectonic%400.17.0)
- [Elan 4.4.0 release](https://github.com/leanprover/elan/releases/tag/v4.4.0)

When updating a bootstrap input, review its upstream revision and release digest
and check the downloaded bytes. These pins establish selected-byte integrity;
they are not a claim of a publisher signature. Keep the artifact's Lean/Mathlib
pins, evaluated dependencies, freeze maps and recorded results unchanged during
workflow maintenance.

## Work in progress

Drafts are not kept in this repository, because its history is public. Work on a draft in a private repository with the same `papers/<slug>/` layout. When the paper is released, add it here in a single commit.
