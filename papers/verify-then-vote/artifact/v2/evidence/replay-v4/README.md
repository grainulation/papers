# Cross-architecture replay, `bran-artifact/4` (content-addressed ids)

Re-run of the `v2/evidence/replay/` matrix (see `../replay/CROSS_ARCH.md`, `bran-artifact/2`) at
HEAD `f4781d082de7a7934c0dc77e431bb7eb29e2f473`, whose default
dumps are `bran-artifact/4`. The old folder is untouched.

**Result.**
- The default dumps for 5 topics (N=100, seed=42) are **byte-identical across all 4 builds**. Every file is tagged `bran-artifact/4`, and each topic has one SHA-256 across the 4 builds.
- Replay matrix: **80/80 PASS** (4 replayers × 4 dumpers × 5 topics).
- Tamper table: **9 cases × 4 builds = 36/36 rejected with the expected exit code**. The diagnostic text, including every recomputed hash, is identical on all 4 builds.
- The new content-id forgery (edit a claim, recompute the root hash, keep the id) is rejected with exit 3 on every build. A sealed SYNTHESIS is also rejected with exit 3 on every build.

**Scope.** As before, everything ran on one physical host (Apple M3 Pro). This is a cross-ISA/OS/libc result, not a cross-machine one. The caveats in `../replay/CROSS_ARCH.md` still apply: Rosetta and Rosetta-for-Linux translation, one rustc family, fixed inputs, an offline Linux build. No timing was measured because the host was shared with a running data collection.

## Builds

| label | target | rustc | OS / runtime | overturn binary sha256 |
|---|---|---|---|---|
| `aarch64-apple-darwin` | aarch64-apple-darwin | 1.93.0 (254b59607 2026-01-19), LLVM 21.1.8 | macOS 26.7.1 (25G241), native | `23c466ea8f68386e195be8533239319202b65c266e340dc3f40e8d14f817b072` |
| `x86_64-apple-darwin-rosetta` | x86_64-apple-darwin (same 1.93.0 toolchain) | 1.93.0 | same macOS, `arch -x86_64` (Rosetta 2; `uname -m` = x86_64) | `208ac04d5d8bf648298c60b6f133018243a31869e156a64840e51d0d2577edcf` |
| `linux-arm64` | aarch64-unknown-linux-gnu | 1.93.1 (01f6ddf75 2026-02-11), LLVM 21.1.8 | Debian 13 `rust:1.93-slim`, glibc 2.41, Docker Desktop 29.8.2, linuxkit 7.0.14 | `ff737bd8709a3be0961e69648b91f237d2c41963d03490a2f34f2e3ca468c7f7` |
| `linux-amd64` | x86_64-unknown-linux-gnu | 1.93.1 | same image for amd64, emulated (`/proc/cpuinfo`: `VirtualApple @ 2.50GHz`) | `a3b4435431aec0493ae0c041af7b6d59327544ca3bd69f3bc2ba0acdd1858b8b` |

All builds use the `release` profile with `--locked`, from a clean `overturn/` at HEAD. The Linux builds run `--offline` from `cargo vendor` output of the same `Cargo.lock`, because TLS interception on this host breaks crates.io inside containers. The staged `src/` was checked with `diff -r` to be identical to `overturn/src`. Per-file source hashes are in `results/platform-darwin.txt`. The Linux binary hashes come from the `sha256sum` file the Dockerfile writes inside each image (`results/platform-linux-*.txt`). The `-v4` image tags keep these images apart from those of `../replay/`.

Records under `results/` were produced when the crate, binary and image tags were named `bran`
(for example `/usr/local/bin/bran` in `results/platform-linux-*.txt`); they are kept as recorded.

## Commands (from the repo root)

```sh
E=v2/evidence/replay-v4
# darwin builds
(cd overturn && cargo build --release --locked && cargo build --release --locked --target x86_64-apple-darwin)
$E/run_platform.sh dump aarch64-apple-darwin        overturn/target/release/overturn
$E/run_platform.sh dump x86_64-apple-darwin-rosetta arch -x86_64 overturn/target/x86_64-apple-darwin/release/overturn

# Linux images (offline, vendored context), built one after the other
$E/stage_context.sh <ctx-dir>
docker buildx build --platform linux/arm64 --load -t overturn-replay-v4:arm64 -f $E/Dockerfile.replay <ctx-dir>
docker buildx build --platform linux/amd64 --load -t overturn-replay-v4:amd64 -f $E/Dockerfile.replay <ctx-dir>
docker run --rm --platform linux/arm64 -v "$PWD/$E:/ev" overturn-replay-v4:arm64 /ev/run_platform.sh dump linux-arm64 overturn
docker run --rm --platform linux/amd64 -v "$PWD/$E:/ev" overturn-replay-v4:amd64 /ev/run_platform.sh dump linux-amd64 overturn

# replay matrix: each build replays every dumps/<build>/ directory
$E/run_platform.sh replay aarch64-apple-darwin        overturn/target/release/overturn
$E/run_platform.sh replay x86_64-apple-darwin-rosetta arch -x86_64 overturn/target/x86_64-apple-darwin/release/overturn
docker run --rm --platform linux/arm64 -v "$PWD/$E:/ev" overturn-replay-v4:arm64 /ev/run_platform.sh replay linux-arm64 overturn
docker run --rm --platform linux/amd64 -v "$PWD/$E:/ev" overturn-replay-v4:amd64 /ev/run_platform.sh replay linux-amd64 overturn

# tamper set (built from the native tcp dump), then replayed by every build
python3 -I $E/tamper.py $E/dumps/aarch64-apple-darwin/tcp.json $E/tamper
$E/run_tamper.sh aarch64-apple-darwin        overturn/target/release/overturn
$E/run_tamper.sh x86_64-apple-darwin-rosetta arch -x86_64 overturn/target/x86_64-apple-darwin/release/overturn
docker run --rm --platform linux/arm64 -v "$PWD/$E:/ev" overturn-replay-v4:arm64 /ev/run_tamper.sh linux-arm64 overturn
docker run --rm --platform linux/amd64 -v "$PWD/$E:/ev" overturn-replay-v4:amd64 /ev/run_tamper.sh linux-amd64 overturn

# --reduce content-id checks (darwin builds; the slim image has no python)
python3 -I v2/evidence/content-ids/check_reduce.py overturn/target/release/overturn $E/dumps/aarch64-apple-darwin/tcp.json <scratch>
python3 -I v2/evidence/content-ids/check_reduce.py overturn/target/x86_64-apple-darwin/release/overturn $E/dumps/x86_64-apple-darwin-rosetta/tcp.json <scratch>

shasum -a 256 $E/dumps/*/*.json > $E/results/dump-sha256.txt
python3 -I $E/compare.py   # writes results/compare.txt; exit 1 on any divergence, non-/4 dump, or unexpected tamper exit
```

## Dumps (identical on all 4 builds; `results/compare.txt`)

| topic | contributions | root_hash | policy_hash | certificate | dump file sha256 |
|---|---|---|---|---|---|
| australia | 158 | `72d1adcba1fefffb903a783c65a97e4a` | `dd8d36e6def3a6d598765e82d461a473` | `42036af57e216ec4` | `8e09c3687565d6fda1095e5d836932a17e522bdcfbe30410074af0b0f0918103` |
| pluto | 158 | `d597dd246286454c0e1fa143c89bbf2f` | `dd8d36e6def3a6d598765e82d461a473` | `755e36a26fb1edb3` | `f47eaf6b5e8fa12311fbe6ddfee191ae3bae8c7274921c953a2b5e57c1151388` |
| tides | 158 | `b4c616a090ea56ad23d05caad34a1a60` | `dd8d36e6def3a6d598765e82d461a473` | `dce7bbc9b940ec2c` | `328de4224d60bf6627b813fd89a1c60aa62e47157d599003cce51e1c59dcd3ca` |
| tcp | 150 | `9bfc91230c6bb7612855ebc548567eb1` | `dd8d36e6def3a6d598765e82d461a473` | `19f12d080acac5d2` | `992016d506c6010a5447966f64e4c3bc28da0876bf8c1ab91ad810300d603cf7` |
| nutrition | 157 | `a2fe7207935918831d3b0744bd5c4f03` | `dd8d36e6def3a6d598765e82d461a473` | `8aa3f15a170e66ec` | `503178491ba3e737a827138ecd3c0f1411cdcd0a67a77d8771974325a77d208f` |

The policy hash is unchanged from `/2`, because content ids change no policy field. The root hashes and certificates differ from the `/2` run. That is expected: the ids are now content ids, and `id_scheme` is part of the root hash.

## Replay matrix (replayer ← dumper, PASS / 5 topics)

| replayer \ dumper | aarch64-apple-darwin | linux-amd64 | linux-arm64 | x86_64-apple-darwin-rosetta |
|---|---|---|---|---|
| aarch64-apple-darwin | 5/5 | 5/5 | 5/5 | 5/5 |
| linux-amd64 | 5/5 | 5/5 | 5/5 | 5/5 |
| linux-arm64 | 5/5 | 5/5 | 5/5 | 5/5 |
| x86_64-apple-darwin-rosetta | 5/5 | 5/5 | 5/5 | 5/5 |

Each replay checks the format tag, recomputes the root hash, checks that every id is its content id and that no SYNTHESIS is sealed, recomputes the policy hash, then re-reduces and compares the output tuples.

## Tamper table (exit codes; `results/tamper-<build>.txt`)

`tamper.py` first checks that its Python re-implementation of `canonical_json` / root hash and of `content_id` (`bran-contribution-id/1`) reproduces the untouched tcp dump: the root hash and all 150 ids. Only then does it build the forgeries, so a "resealed" case is a consistent forgery of everything except the targeted check.

| case | edit | expected | aarch64-darwin | x86_64-rosetta | linux-arm64 | linux-amd64 | rejection |
|---|---|---|---|---|---|---|---|
| claim-edit-unsealed | `contributions[0].canonical_form.object += "x"`; id and root kept | 3 | 3 | 3 | 3 | 3 | root hash mismatch (recomputed `32eb585d9cb0a071bd72cc9490fe55c1`) |
| **claim-edit-resealed-kept-id** | same edit, **root hash recomputed**, id kept | 3 | 3 | 3 | 3 | 3 | contribution id mismatch: `2458d18c…` is not its content id `8ddcb180e2f28231c2bcf5ebffb70728` |
| **synthesis-in-set** | `contributions[0].kind = SYNTHESIS`, id = its content id, root recomputed | 3 | 3 | 3 | 3 | 3 | `ff4d8ae2b8422c6f462a568480567182: SYNTHESIS is out of scope for the reducer` |
| claim-edit-resealed-new-id | same edit, id = new content id, root recomputed, outputs kept | 1 | 1 | 1 | 1 | 1 | output tuples differ (cert `e616c8dad1b5dd23` vs `19f12d080acac5d2`; admitted 15 vs 14) |
| policy-deadband-501 | `policy.deadband_threshold` 500 → 501, policy_hash kept | 4 | 4 | 4 | 4 | 4 | POLICY MISMATCH, recomputed `1b2514b73a22f98e6bab7573fea62bb1` (same as the `/2` run) |
| seq-plus-1000 | `contributions[0].seq += 1000`, root kept | 3 | 3 | 3 | 3 | 3 | root hash mismatch (`78974e3605719e85e3dcb3a26856d20a`) |
| winner-swap | first contested selection's stored `winner` set to another member | 1 | 1 | 1 | 1 | 1 | output tuples differ (1 selection) |
| scheme-strip-v2-tag | `artifact.id_scheme` removed, format retagged `/2`, root kept | 3 | 3 | 3 | 3 | 3 | root hash mismatch (`95338e7f6b9782a382a3b4fd6a122275`): the scheme is sealed |
| format-retag-only | format retagged `/2`, id_scheme kept | 1 | 1 | 1 | 1 | 1 | unsupported format |

Exit codes: 1 = format or output mismatch, 3 = root hash, record or content id mismatch, 4 = policy hash mismatch. The stderr lines are byte-identical across the 4 builds once the file path prefix (`/ev` vs host path) is removed; all four hash to `622798ae…`.

Note: this table records the binary at f4781d0, where `format-retag-only` exited 1 with "unsupported format bran-artifact/2 (expected bran-artifact/2, …)". Since the CLI cleanup that followed, the same case exits **5** with "format tag bran-artifact/2 does not match content (expected bran-artifact/4)", and fresh `/4` dumps carry an `envelope_hash`, so dump file hashes differ from the column above. Root hashes, policy hashes and certificates are unchanged; `make replay-file` checks the new behaviour.

`--reduce` path (`results/reduce-check-*.txt`, darwin native and Rosetta): 6/6 PASS on both builds. That run covers:
- reproducing the dump's root and certificate
- the kept-id edit rejected with exit 2
- `--assign-ids` reproducing the ids
- SYNTHESIS dropped at P3 with `synthesis_out_of_scope`
- both legacy (no `id_scheme`) paths

## Files

- `run_platform.sh`: dump/replay driver, copied unchanged from `../replay/`
- `compare.py`: `/4` variant. It also asserts the `/4` format tag and summarizes the tamper table.
- `Dockerfile.replay`, `stage_context.sh`: as in `../replay/`. The Dockerfile also writes `/overturn-sha256.txt`, and the image tags are `-v4`.
- `tamper.py`, `run_tamper.sh`, `tamper/`: tamper builder and driver, the 9 tampered files, and `expected.tsv`
- `dumps/<build>/<topic>.json`: the 20 `bran-artifact/4` dumps
- `results/`: dump, replay, tamper and reduce-check logs per build, `compare.txt`, `dump-sha256.txt`, `platform-*.txt`, `build-linux-*.log`
