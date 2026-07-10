#!/usr/bin/env bash
# Shallow-clone Nextflow into vendor/ as a local reference for its DSL2 semantics.
# nf-chain generates Nextflow; it does not link against this source.
set -euo pipefail

REPO="https://github.com/nextflow-io/nextflow.git"
DEST="$(cd "$(dirname "$0")/.." && pwd)/vendor/nextflow"

if [ -d "$DEST/.git" ]; then
    echo "vendor/nextflow already present; pulling"
    git -C "$DEST" pull --ff-only --depth 1
else
    mkdir -p "$(dirname "$DEST")"
    git clone --depth 1 "$REPO" "$DEST"
fi

git -C "$DEST" log -1 --format='vendored nextflow @ %h (%ad)' --date=short
