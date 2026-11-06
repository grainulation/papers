# Cross-architecture replay of sealed overturn artifacts

**Result.** All 5 topics (N=100, seed=42) were dumped by four builds: aarch64-apple-darwin, x86_64-apple-darwin under Rosetta, linux/arm64 and linux/amd64. The 20 dump files are **byte-identical**: one SHA-256 per topic across all four builds. Every build also replayed every other build's dumps (4 replayers × 4 dumpers × 5 topics = 80 replays), and all 80 passed. Each replay recomputed the root hash and the policy hash and re-reduced the artifact, and the output tuples were struct-equal to the stored ones. A tampered policy was rejected with exit 4 (POLICY MISMATCH) on every build, and every build computed the same hash for the tampered policy.

**Scope.** This checks determinism across instruction sets, operating systems and libc, and across two rustc patch releases. All of it ran on **one physical host** (Apple M3 Pro). It is not a cross-machine result. See Caveats.

## What is compared

Artifact format `bran-artifact/2`. The dump holds the sealed set, the policy, `policy_hash`, and `outputs` (root_hash, policy_hash, certificate, admitted and rejected ids, and per-slot selections with quantized scores). The fields mean the following:

- `root_hash` = SHA-256 over the canonical JSON of the sealed set, truncated to 128 bits.
- `policy_hash` = SHA-256 over `OverturnCompiler::canonical_policy_json()` (`bran-policy/1`), truncated to 128 bits. The canonical policy has two sections, sorted by key and written without whitespace:
  - `config`: every `OverturnCompiler` field. That covers the weights, severity budget, deadband, Schulze epsilon, hardening, and the incompatible_values table with each group's objects sorted and deduplicated.
  - `constants`: values compiled into the binary. These are the score scale, lowering factors, evidence-type weights, verification-quality table, and the sorted list of functional predicates.

  Floats are written in serde_json/ryu shortest round-trip decimal form. This is exact (two different f64 values never print the same string) and platform-independent. Non-finite floats are rejected.
- `certificate` = SHA-256(root_hash ‖ policy_hash ‖ admitted ids, in admitted order, as UTF-8 hex/id strings), truncated to 64 bits.

## Platforms

| label | target | rustc | OS | how it ran |
|---|---|---|---|---|
| `aarch64-apple-darwin` | aarch64-apple-darwin | 1.93.0 (254b59607 2026-01-19), LLVM 21.1.8 | macOS 26.7.1 (25G241), Darwin 25.6.0 | native, Apple M3 Pro |
| `x86_64-apple-darwin-rosetta` | x86_64-apple-darwin (cross-compiled with the same 1.93.0 toolchain) | 1.93.0 | same macOS | `arch -x86_64`. The binary is an x86_64-only Mach-O, so it can only run translated by Rosetta 2 |
| `linux-arm64` | aarch64-unknown-linux-gnu | 1.93.1 (01f6ddf75 2026-02-11), LLVM 21.1.8 | Debian 13 (trixie), `rust:1.93-slim`, linuxkit kernel 7.0.14 | Docker Desktop 29.8.2 VM, native arm64 |
| `linux-amd64` | x86_64-unknown-linux-gnu | 1.93.1 | Debian 13 (trixie), same image for amd64 | Docker Desktop, emulated. `/proc/cpuinfo` reports `VirtualApple @ 2.50GHz`, which means Rosetta-for-Linux translation |

Every build uses the `release` profile (opt-level 3, LTO) and `Cargo.lock` with `--locked`. The Linux builds are offline from vendored crates; see the note on the build below. All four builds use the same source tree; `results/platform-darwin.txt` has the SHA-256 of every source file. Full version details are in `results/platform-*.txt`.

Records under `results/` were produced when the crate, binary and image tags were named `bran`
(for example `/usr/local/bin/bran` in `results/platform-linux-*.txt`); they are kept as recorded.

## Commands

From the repo root:

```sh
# native and Rosetta builds
cd overturn && cargo build --release && cargo build --release --target x86_64-apple-darwin && cd ..
E=v2/evidence/replay
$E/run_platform.sh dump aarch64-apple-darwin        overturn/target/release/overturn
$E/run_platform.sh dump x86_64-apple-darwin-rosetta arch -x86_64 overturn/target/x86_64-apple-darwin/release/overturn

# Linux images, built offline from a vendored context
$E/stage_context.sh /tmp/overturn-ctx
docker buildx build --platform linux/arm64 --load -t overturn-replay:arm64 -f $E/Dockerfile.replay /tmp/overturn-ctx
docker buildx build --platform linux/amd64 --load -t overturn-replay:amd64 -f $E/Dockerfile.replay /tmp/overturn-ctx
docker run --rm --platform linux/arm64 -v "$PWD/$E:/ev" overturn-replay:arm64 /ev/run_platform.sh dump linux-arm64 overturn
docker run --rm --platform linux/amd64 -v "$PWD/$E:/ev" overturn-replay:amd64 /ev/run_platform.sh dump linux-amd64 overturn

# full replay matrix: each build replays every dumps/<platform>/ directory
$E/run_platform.sh replay aarch64-apple-darwin        overturn/target/release/overturn
$E/run_platform.sh replay x86_64-apple-darwin-rosetta arch -x86_64 overturn/target/x86_64-apple-darwin/release/overturn
docker run --rm --platform linux/arm64 -v "$PWD/$E:/ev" overturn-replay:arm64 /ev/run_platform.sh replay linux-arm64 overturn
docker run --rm --platform linux/amd64 -v "$PWD/$E:/ev" overturn-replay:amd64 /ev/run_platform.sh replay linux-amd64 overturn

python3 -I $E/compare.py      # writes results/compare.txt; exit 1 on any divergence
```

## Results

Hashes are identical on all four platforms (from `results/compare.txt`):

| topic | root_hash | policy_hash | certificate | dump file sha256 | identical on all 4 |
|---|---|---|---|---|---|
| australia | `532f3bd404394d35a20427bf56f2b55b` | `dd8d36e6def3a6d598765e82d461a473` | `69d66ca2f0c5914b` | `6635ae4dd5f65ca273b0c02908687cb8d1fd7c9b2ffa6229d5b8f6254c5a3491` | yes |
| pluto | `ab104a2a5aff10ad87ed2991ecd57fdc` | `dd8d36e6def3a6d598765e82d461a473` | `442c680ba28c2a09` | `e2835eb7a1c56876856d28272f116670068c9b4ba72e2eb9ddb68bf916e7310d` | yes |
| tides | `a0c30a5b0a2a2f9a88188de3ce194bff` | `dd8d36e6def3a6d598765e82d461a473` | `6ad8e9595e7a8643` | `13e1ed47402d5dc1acf6d85a23d555dfb9cdc6756ed6592bdb88ae5f36b53441` | yes |
| tcp | `a0a3b9e2f383676a565bd129bbe78adf` | `dd8d36e6def3a6d598765e82d461a473` | `3acd534f21f3664b` | `5acbfbe6604d79919b54cb2c059d2f1ad8f32cb82a54c08fd235030fb65b11bc` | yes |
| nutrition | `12b06f9eb6e1a3d05d2ec279b97ef388` | `dd8d36e6def3a6d598765e82d461a473` | `4105c6fbc2b09611` | `3fe8887258cd1572868b964334c1208c507fdd9c1a0977eee794a7ef19f590b0` | yes |

The dump file contains everything in `outputs`, including every selection's quantized scores. Byte-identical files therefore mean identical output tuples. All 20 per-file hashes are in `results/dump-sha256.txt`.

Replay matrix (replayer ← dumper, PASS / 5 topics):

| replayer \ dumper | aarch64-apple-darwin | linux-amd64 | linux-arm64 | x86_64-apple-darwin-rosetta |
|---|---|---|---|---|
| aarch64-apple-darwin | 5/5 | 5/5 | 5/5 | 5/5 |
| linux-amd64 | 5/5 | 5/5 | 5/5 | 5/5 |
| linux-arm64 | 5/5 | 5/5 | 5/5 | 5/5 |
| x86_64-apple-darwin-rosetta | 5/5 | 5/5 | 5/5 | 5/5 |

The matrix covers both directions: the native build replays dumps from x86_64 and Linux, and those builds replay the native dumps.

Policy tamper check (`results/policy-tamper-cross.txt`): in the native tcp dump, `policy.deadband_threshold` was changed from 500 to 501 and the stored hash was left unchanged. linux-arm64, linux-amd64 and x86_64-rosetta each rejected the file with exit 4 and recomputed the same hash, `1b2514b73a22f98e6bab7573fea62bb1`. `make replay-file` gives the same value on native. So the policy hash is platform-independent for a non-default policy as well.

## Caveats

- **Cross-architecture, not cross-machine.** All four builds ran on one Apple M3 Pro. Rosetta 2 runs on the same OS and the same machine. The linux/amd64 build runs under Docker Desktop's Rosetta-for-Linux translation (CPU reported as `VirtualApple`) on the same host. A translator could in principle reproduce host floating-point behavior that real x86 hardware would not. In practice, x86_64 SSE2 and aarch64 doubles are both IEEE-754 binary64 with round-to-nearest, and the scores are quantized to integers ×10,000 before any comparison. Even so, this run does not test real x86 silicon or a second machine.
- **One compiler family.** Two rustc patch releases were used: 1.93.0 on darwin and 1.93.1 on Linux, both with LLVM 21.1.8. Other major rustc/LLVM versions were not tested.
- **Fixed inputs.** The check covers 5 topics at N=100 and seed=42 only, under the default policy, plus one tampered policy.
- **Linux build is offline.** In-container `cargo` could not reach crates.io: TLS interception on this host ("self-signed certificate in certificate chain"). The Linux images are therefore built with `--offline` from `cargo vendor` output of the same `Cargo.lock` (`stage_context.sh`). Dependency versions are identical, but the sources come from the host's registry cache.
- **No timing.** No timing was measured; the CPU was shared with another job.

## Files

- `run_platform.sh`: dump/replay driver (POSIX sh, used on every platform)
- `compare.py`: byte-level comparison and matrix summary
- `Dockerfile.replay`, `stage_context.sh`: replay-only Linux image. The Dockerfile is self-contained: it builds from the context that `stage_context.sh` stages.
- `dumps/<platform>/<topic>.json`: the 20 dumped artifacts
- `results/`: per-platform dump and replay logs, `compare.txt`, `dump-sha256.txt`, `policy-tamper-cross.txt`, `platform-*.txt`, `build-linux-*.log`
