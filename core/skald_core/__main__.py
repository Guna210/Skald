"""Entry point for `python -m skald_core`."""

import argparse
import sys

from skald_core import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="skald_core", add_help=False)
    parser.add_argument("--version", action="store_true")
    args, unknown = parser.parse_known_args(argv)
    if args.version and not unknown:
        sys.stdout.write(f"{__version__}\n")
        return 0
    sys.stderr.write("Usage: python -m skald_core --version\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
