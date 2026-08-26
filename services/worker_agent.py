"""Compatibility entrypoint delegating to the canonical worker CLI."""

import os
import socket
import sys

from cli.worker import main

__all__ = ["run"]


def run(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        capabilities = os.environ.get("DOR_WORKER_CAPABILITIES", "").strip()
        if not capabilities:
            raise RuntimeError("DOR_WORKER_CAPABILITIES must be configured")
        args = [
            "--id",
            os.environ.get("DOR_WORKER_ID", "").strip() or socket.gethostname(),
            "--caps",
            capabilities,
        ]
    return main(args)


if __name__ == "__main__":
    sys.exit(run())
