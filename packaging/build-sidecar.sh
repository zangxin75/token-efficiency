#!/usr/bin/env bash
# tokeneff sidecar 打包脚本（PyInstaller onefile）。
#
# 用法: ./packaging/build-sidecar.sh
# 产物: dist/tokeneff-sidecar (Linux) / tokeneff-sidecar.exe (Windows，需在 Windows 上跑)
#
# 关键: 通过 --additional-hooks-dir 注入 keyring hook（H1），
#       否则打包后 keyrings.alt 兜底后端丢失，API key 无法存储。

set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON=".venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi

echo "=== 安装/确认 PyInstaller ==="
"$PYTHON" -m pip install -q pyinstaller 2>&1 | tail -2 || true

echo "=== 清理旧产物 ==="
rm -rf packaging/pyinstaller_build dist/tokeneff-sidecar*

echo "=== 打包 sidecar（onefile + keyring hook）==="
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
echo "=== 产物 ==="
ls -lh dist/tokeneff-sidecar* 2>/dev/null || echo "（无产物，打包失败）"
