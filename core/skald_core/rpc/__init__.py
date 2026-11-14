"""JSON-RPC 2.0 stdio server package for Skald core."""

from skald_core.rpc.server import (
    APP_ERROR,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    InvalidParamsError,
    RpcServer,
    SkaldError,
    configure_logging,
    notify,
    run_stdio_server,
)

__all__ = [
    "APP_ERROR",
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "METHOD_NOT_FOUND",
    "PARSE_ERROR",
    "InvalidParamsError",
    "RpcServer",
    "SkaldError",
    "configure_logging",
    "notify",
    "run_stdio_server",
]
