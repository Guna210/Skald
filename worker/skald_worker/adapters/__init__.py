"""Adapter registry and loader for Skald workers."""

from __future__ import annotations

from skald_worker.protocol import Adapter

# Read by `skald_core.catalog.validate` via `ast.literal_eval` — keep as a dict literal.
# Real model adapters are added in T04.x; the `fake` adapter is intentionally omitted here
# so the catalog and app never offer it.
ADAPTER_VERSIONS: dict[str, str] = {}


def load_adapter(name: str) -> Adapter:
    """Instantiate an adapter by name, raising KeyError/ImportError if unavailable."""
    if name == "fake":
        from skald_worker.adapters.fake import FakeAdapter

        return FakeAdapter()
    if name not in ADAPTER_VERSIONS:
        raise KeyError(f"Unknown adapter: {name!r}")
    raise KeyError(f"Adapter {name!r} has no loader wired yet.")


__all__ = ["ADAPTER_VERSIONS", "load_adapter"]
