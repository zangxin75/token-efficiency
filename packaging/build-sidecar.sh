#!/usr/bin/env bash
# tokeneff sidecar build script (PyInstaller onefile).
#
# Usage: ./packaging/build-sidecar.sh
# Output: dist/tokeneff-sidecar (Linux) / tokeneff-sidecar.exe (Windows, must run on Windows)
#
# Key: injects the keyring hook via --additional-hooks-dir (H1),
#      otherwise the keyrings.alt fallback backend is missing after build and API keys cannot be stored.

set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON=".venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi

echo "=== Install / verify PyInstaller ==="
"$PYTHON" -m pip install -q pyinstaller 2>&1 | tail -2 || true

echo "=== Clean previous build artifacts ==="
rm -rf packaging/pyinstaller_build dist/tokeneff-sidecar*

echo "=== Build sidecar (onefile + keyring hook) ==="
"$PYTHON" -m PyInstaller \
  --onefile \
  --name tokeneff-sidecar \
  --additional-hooks-dir packaging/hooks \
  --hidden-import uvicorn.logging \
  --hidden-import uvicorn.loops \
  --hidden-import uvicorn.loops.auto \
  --hidden-import uvicorn.protocols \
  --hidden-import uvicorn.protocols.http \
  --hidden-import uvicorn.protocols.http.auto \
  --hidden-import uvicorn.protocols.websockets \
  --hidden-import uvicorn.protocols.websockets.auto \
  --hidden-import uvicorn.lifespan \
  --hidden-import uvicorn.lifespan.on \
  --collect-submodules tokeneff \
  --distpath dist \
  --workpath packaging/pyinstaller_build \
  --noconfirm \
  packaging/sidecar_entry.py

echo ""
echo "=== Build artifacts ==="
ls -lh dist/tokeneff-sidecar* 2>/dev/null || echo "(no artifacts, build failed)"
