"""tokeneff sidecar entry point (for PyInstaller packaging).

This file is the PyInstaller entry point; main() is compiled into a single-file executable.
Business logic lives in tokeneff.api.local_server.
"""

import sys


def main():
    from tokeneff.api.local_server import run_sidecar

    # Allow external port specification (called by Tauri)
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1", help="bind address")
    parser.add_argument("--port", type=int, default=7861, help="API port")
    args = parser.parse_args()

    run_sidecar(host=args.host, preferred_port=args.port)


if __name__ == "__main__":
    main()
