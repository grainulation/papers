#!/bin/sh
# Stage an offline Docker build context for Dockerfile.replay:
# overturn/{Cargo.toml,Cargo.lock,src} + `cargo vendor` + .cargo/config.toml.
set -eu
CTX=$1
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
rm -rf "$CTX"; mkdir -p "$CTX/overturn/.cargo"
cp -R "$REPO/overturn/Cargo.toml" "$REPO/overturn/Cargo.lock" "$REPO/overturn/src" "$CTX/overturn/"
(cd "$CTX/overturn" && cargo vendor --locked vendor > .cargo/config.toml)
