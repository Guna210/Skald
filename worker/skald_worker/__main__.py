"""CLI entry point for `python -m skald_worker --adapter <name> [--check]`."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from skald_worker import __version__
from skald_worker.adapters import load_adapter
from skald_worker.protocol import WorkerRpcServer, protect_stdout


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stderr,
        force=True,
    )


def _run_check(adapter_name: str) -> int:
    # Ensure nothing printed during adapter import or dependency checks leaks to stdout.
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    try:
        adapter = load_adapter(adapter_name)
        adapter.check_dependencies()
        devices = adapter.device_options()
    except Exception as exc:
        sys.stderr.write(f"Worker check failed for adapter {adapter_name!r}: {exc}\n")
        sys.stderr.flush()
        return 1

    payload = {
        "ok": True,
        "adapter": adapter.name,
        "adapter_version": adapter.version,
        "worker_version": __version__,
        "devices": devices,
    }
    sys.stderr.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stderr.flush()
    return 0


def _run_server(adapter_name: str) -> int:
    rpc_fd = protect_stdout()
    _configure_logging()
    logger = logging.getLogger(__name__)

    try:
        adapter = load_adapter(adapter_name)
    except Exception as exc:
        logger.error("Failed to load adapter %r: %s", adapter_name, exc)
        os.close(rpc_fd)
        return 1

    rpc_out = os.fdopen(rpc_fd, "wb", buffering=0)
    try:
        server = WorkerRpcServer(adapter=adapter, stdin=sys.stdin.buffer, stdout=rpc_out)
        logger.info("Skald worker started for adapter %r", adapter_name)
        server.serve()
    finally:
        logger.info("Skald worker stopping for adapter %r", adapter_name)
        rpc_out.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="skald_worker",
        description="Skald TTS model worker process.",
    )
    parser.add_argument(
        "--adapter",
        required=True,
        help="Adapter name to run (e.g. 'fake' or a catalog family adapter).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the adapter imports and dependencies are present, then exit.",
    )
    args = parser.parse_args(argv)

    if args.check:
        return _run_check(args.adapter)
    return _run_server(args.adapter)


if __name__ == "__main__":
    raise SystemExit(main())
