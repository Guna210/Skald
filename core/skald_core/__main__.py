"""Entry point for `python -m skald_core`."""

import sys

from skald_core import __version__
from skald_core.rpc.server import run_stdio_server


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        return run_stdio_server()
    if args == ["--version"]:
        sys.stdout.write(f"{__version__}\n")
        return 0
    sys.stderr.write("Usage: python -m skald_core [--version]\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
