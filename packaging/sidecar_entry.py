"""tokeneff sidecar 入口点（PyInstaller 打包用）。

此文件是 PyInstaller 的入口，main() 被编译成单文件可执行。
业务逻辑在 tokeneff.api.local_server。
"""

import sys


def main():
    from tokeneff.api.local_server import run_sidecar

    # 允许外部指定端口（供 Tauri 调用）
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1", help="绑定地址")
    parser.add_argument("--port", type=int, default=7861, help="API 端口")
    args = parser.parse_args()

    run_sidecar(host=args.host, preferred_port=args.port)


if __name__ == "__main__":
    main()
