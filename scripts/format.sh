#!/bin/bash

# Format frontend code with Prettier (writes changes in place).
# Scope: frontend/**/*.{html,css,js}. Backend Python is not touched.

# Resolve repo root so the script works from any cwd.
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

if [ ! -d "node_modules" ]; then
    echo "node_modules/ missing — run 'npm install' at the repo root first."
    exit 1
fi

echo "Formatting frontend files with Prettier..."
npx prettier --write "frontend/**/*.{html,css,js}"
echo "Done."
