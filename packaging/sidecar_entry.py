"""tokeneff sidecar entry point (for PyInstaller packaging).

This file is the PyInstaller entry point; main() is compiled into a single-file executable.
Business logic lives in tokeneff.api.local_server.
"""

import sys


def main():
    from tokeneff.api.local_server import run_sidecar

    # Port may be specified externally; host is intentionally NOT configurable —
    # the API writes provider keys into the system keyring and must never be
    # exposed beyond loopback (★ review fix: removed the --host option that could
    # bind 0.0.0.0 and expose key-writing endpoints to the LAN).
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7861, help="API port")
    args = parser.parse_args()

    run_sidecar(host="127.0.0.1", preferred_port=args.port)


if __name__ == "__main__":
    main()
