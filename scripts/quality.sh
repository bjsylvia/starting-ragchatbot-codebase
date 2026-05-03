#!/bin/bash

# Check that frontend code is formatted. Exits non-zero on drift
# so this script can be wired into CI later.
# Scope: frontend/**/*.{html,css,js}. Backend Python is not checked.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

if [ ! -d "node_modules" ]; then
    echo "node_modules/ missing — run 'npm install' at the repo root first."
    exit 1
fi

echo "Checking frontend formatting with Prettier..."
npx prettier --check "frontend/**/*.{html,css,js}"
status=$?

if [ $status -eq 0 ]; then
    echo "All frontend files are properly formatted."
else
    echo "Formatting drift detected. Run ./scripts/format.sh to fix."
fi

exit $status
