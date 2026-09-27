#!/usr/bin/env bash
# Publish scrapex to PyPI.
#
# Usage:
#   export TWINE_USERNAME=__token__
#   export TWINE_PASSWORD=pypi-...
#   ./scripts/publish-pypi.sh            # production PyPI
#   ./scripts/publish-pypi.sh --test     # TestPyPI first
#
# Requires:
#   - twine + build installed (in [dev] extra)
#   - PyPI token in TWINE_PASSWORD (or ~/.pypirc configured)
#
# What this script does:
#   1. Cleans dist/
#   2. Builds sdist + wheel
#   3. Runs twine check (must pass)
#   4. Uploads to PyPI (or TestPyPI with --test)

set -euo pipefail

cd "$(dirname "$0")/.."

TESTPYPI=false
if [ "${1:-}" = "--test" ]; then
    TESTPYPI=true
fi

echo "==> Cleaning dist/"
rm -rf dist/ build/

echo "==> Building sdist + wheel"
python -m build --sdist --wheel --outdir dist/

echo "==> Checking package metadata"
twine check dist/*

echo "==> Uploading"
if [ "$TESTPYPI" = true ]; then
    echo "    (to TestPyPI)"
    twine upload --repository testpypi dist/*
else
    echo "    (to PyPI)"
    twine upload dist/*
fi

echo "==> Done"
echo "    https://pypi.org/project/scrapex/"