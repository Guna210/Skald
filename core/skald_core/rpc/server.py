"""JSON-RPC 2.0 newline-delimited stdio server."""

from __future__ import annotations

import io
import json
import logging
import logging.handlers
import os
import sys
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, cast

from pydantic import BaseModel, ValidationError

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
APP_ERROR = -32000

_MANAGED_HANDLER_ATTR = "_skald_managed"
_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

logger = logging.getLogger(__name__)

JsonId = str | int | float | None
HandlerFn = Callable[..., Any]

_active_server_lock = threading.Lock()
_active_server: RpcServer | None = None


class SkaldError(Exception):
    """Application-level error mapped to JSON-RPC error code -32000."""

    def __init__(
        self,
        kind: str,
        message: str,
        details: Any = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.details = details
        self.hint = hint

    def to_error_dict(self) -> dict[str, Any]:
        return {
            "code": APP_ERROR,
            "message": self.message,
            "data": {
                "kind": self.kind,
                "details": self.details,
                "hint": self.hint,
            },
        }


@dataclass(frozen=True)
class _MethodEntry:
    handler: HandlerFn
    params_model: type[BaseModel] | None
    result_model: type[BaseModel] | None


def _default_log_dir() -> Path:
    env_dir = os.environ.get("SKALD_LOG_DIR", "").strip()
    if env_dir:
        return Path(env_dir)
    return Path(tempfile.gettempdir()) / "skald" / "logs"


def close_managed_logging() -> None:
    """Flush, close, and remove logging handlers installed by configure_logging."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _MANAGED_HANDLER_ATTR, False):
            root.removeHandler(handler)
            try:
                handler.flush()
            finally:
                handler.close()


def configure_logging(log_dir: Path | None = None, level: int = logging.INFO) -> Path:
    """Configure rotating file logging (in SKALD_LOG_DIR or temp dir) and stderr logging."""
    target_dir = _default_log_dir() if log_dir is None else log_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    log_file = target_dir / "skald-core.log"

    close_managed_logging()

    formatter = logging.Formatter(_LOG_FORMAT)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    setattr(file_handler, _MANAGED_HANDLER_ATTR, True)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    setattr(stderr_handler, _MANAGED_HANDLER_ATTR, True)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(stderr_handler)
    return log_file


def _unwrap_stream(stream: IO[bytes] | IO[str]) -> tuple[IO[bytes] | IO[str], IO[bytes] | IO[str]]:
    """Return (underlying_stream, owner_ref), using .buffer on TextIOBase when available."""
    if isinstance(stream, io.TextIOBase) and hasattr(stream, "buffer"):
        buf = stream.buffer
        if buf is not None:
            return buf, stream
    return stream, stream


def _error_response(
    req_id: JsonId,
    code: int,
    message: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": error}


def _is_valid_id(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (str, int, float, type(None)))


def _serialize_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class RpcServer:
    """Thread-safe newline-delimited JSON-RPC 2.0 server over stdio."""

    def __init__(
        self,
        stdin: IO[bytes] | IO[str] | None = None,
        stdout: IO[bytes] | IO[str] | None = None,
    ) -> None:
        raw_in: IO[bytes] | IO[str] = sys.stdin if stdin is None else stdin
        raw_out: IO[bytes] | IO[str] = sys.stdout if stdout is None else stdout
        self._stdin, self._stdin_owner = _unwrap_stream(raw_in)
        self._stdout, self._stdout_owner = _unwrap_stream(raw_out)
        self._write_lock = threading.Lock()
        self._shutdown_event = threading.Event()
        self._methods: dict[str, _MethodEntry] = {}

        self.register("system.shutdown", self._handle_shutdown)

    def _handle_shutdown(self) -> dict[str, bool]:
        self.request_shutdown()
        return {"ok": True}

    def register(
        self,
        method_name: str,
        handler: HandlerFn,
        params_model: type[BaseModel] | None = None,
        result_model: type[BaseModel] | None = None,
    ) -> None:
        """Register an RPC method with optional Pydantic params and result models."""
        self._methods[method_name] = _MethodEntry(
            handler=handler,
            params_model=params_model,
            result_model=result_model,
        )

    def request_shutdown(self) -> None:
        """Signal the server read loop to exit cleanly after the current message."""
        self._shutdown_event.set()

    def _write_line(self, line: str) -> None:
        with self._write_lock:
            if isinstance(self._stdout, io.TextIOBase):
                self._stdout.write(line + "\n")
            else:
                cast(IO[bytes], self._stdout).write((line + "\n").encode("utf-8"))
            self._stdout.flush()

    def _write_message(self, payload: dict[str, Any]) -> None:
        try:
            encoded = _serialize_json(payload)
        except TypeError as exc:
            logger.exception("Failed to serialize JSON-RPC payload")
            if "id" in payload:
                fallback = _error_response(
                    payload["id"],
                    INTERNAL_ERROR,
                    "Internal error",
                    {"kind": "internal", "details": str(exc), "hint": None},
                )
                self._write_line(_serialize_json(fallback))
                return
            raise
        self._write_line(encoded)

    def notify(
        self,
        method: str,
        params: BaseModel | dict[str, Any] | list[Any] | None = None,
    ) -> None:
        """Write a JSON-RPC 2.0 notification to stdout under the write lock."""
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = (
                params.model_dump(mode="json") if isinstance(params, BaseModel) else params
            )
        self._write_message(payload)

    def handle_line(self, raw_line: str) -> dict[str, Any] | None:
        """Parse and dispatch a single JSON-RPC 2.0 line, returning a response or None."""
        if not raw_line.strip():
            return None

        try:
            msg = json.loads(raw_line)
        except json.JSONDecodeError:
            return _error_response(None, PARSE_ERROR, "Parse error")

        if not isinstance(msg, dict):
            # Batches (JSON arrays) and non-object values are rejected as Invalid Request.
            return _error_response(None, INVALID_REQUEST, "Invalid Request")

        has_id = "id" in msg
        raw_id = msg.get("id")
        if has_id and not _is_valid_id(raw_id):
            return _error_response(None, INVALID_REQUEST, "Invalid Request")

        req_id: JsonId = raw_id if has_id else None

        if msg.get("jsonrpc") != "2.0":
            return _error_response(req_id, INVALID_REQUEST, "Invalid Request")

        method = msg.get("method")
        if not isinstance(method, str) or not method:
            return _error_response(req_id, INVALID_REQUEST, "Invalid Request")

        entry = self._methods.get(method)
        if entry is None:
            if not has_id:
                logger.warning("Ignoring notification for unknown method %r", method)
                return None
            return _error_response(req_id, METHOD_NOT_FOUND, f"Method not found: {method}")

        raw_params = msg.get("params")
        validated_params: BaseModel | None = None

        if entry.params_model is not None:
            candidate = {} if raw_params is None else raw_params
            try:
                validated_params = entry.params_model.model_validate(candidate)
            except ValidationError as exc:
                if not has_id:
                    logger.warning("Ignoring notification %r with invalid params", method)
                    return None
                details = json.loads(exc.json(include_url=False))
                return _error_response(
                    req_id,
                    INVALID_PARAMS,
                    "Invalid params",
                    {"details": details},
                )
        elif raw_params not in (None, {}):
            if not has_id:
                logger.warning("Ignoring notification %r with unexpected params", method)
                return None
            return _error_response(
                req_id,
                INVALID_PARAMS,
                "Invalid params",
                {"details": [{"msg": "Method takes no parameters"}]},
            )

        try:
            if entry.params_model is not None:
                result = entry.handler(validated_params)
            else:
                result = entry.handler()
        except SkaldError as exc:
            logger.warning("RPC error in %s (%s): %s", method, exc.kind, exc.message)
            if not has_id:
                return None
            return {"jsonrpc": "2.0", "id": req_id, "error": exc.to_error_dict()}
        except Exception as exc:
            logger.exception("Unhandled error in RPC method %s", method)
            if not has_id:
                return None
            return _error_response(
                req_id,
                INTERNAL_ERROR,
                "Internal error",
                {"kind": "internal", "details": str(exc), "hint": None},
            )

        if not has_id:
            return None

        try:
            if entry.result_model is not None:
                if isinstance(result, entry.result_model):
                    serialized: Any = result.model_dump(mode="json")
                else:
                    serialized = entry.result_model.model_validate(result).model_dump(mode="json")
            elif isinstance(result, BaseModel):
                serialized = result.model_dump(mode="json")
            else:
                serialized = result
        except ValidationError as exc:
            logger.exception("Result validation failed for %s", method)
            return _error_response(
                req_id,
                INTERNAL_ERROR,
                "Internal error",
                {"kind": "internal", "details": str(exc), "hint": None},
            )

        return {"jsonrpc": "2.0", "id": req_id, "result": serialized}

    def _read_line(self) -> str | None:
        raw = self._stdin.readline()
        if isinstance(raw, bytes):
            if raw == b"":
                return None
            return raw.decode("utf-8")
        if raw == "":
            return None
        return raw

    def serve(self) -> None:
        """Read JSON-RPC requests from stdin until EOF or shutdown."""
        global _active_server
        with _active_server_lock:
            prev_server = _active_server
            _active_server = self
        try:
            while not self._shutdown_event.is_set():
                try:
                    line = self._read_line()
                except UnicodeDecodeError:
                    self._write_message(_error_response(None, PARSE_ERROR, "Parse error"))
                    continue
                if line is None:
                    break
                response = self.handle_line(line)
                if response is not None:
                    self._write_message(response)
        finally:
            with _active_server_lock:
                _active_server = prev_server


def notify(
    method: str,
    params: BaseModel | dict[str, Any] | list[Any] | None = None,
) -> None:
    """Send a JSON-RPC notification through the active stdio server, if any."""
    with _active_server_lock:
        server = _active_server
    if server is None:
        logger.debug("Notification dropped (no active RPC server): %s", method)
        return
    server.notify(method, params)


def run_stdio_server(setup: Callable[[RpcServer], None] | None = None) -> int:
    """Redirect stdout to stderr, configure logging, and run the JSON-RPC stdio loop."""
    real_stdout = sys.stdout
    sys.stdout = sys.stderr
    configure_logging()
    server = RpcServer(stdin=sys.stdin, stdout=real_stdout)
    if setup is not None:
        setup(server)
    logger.info("Skald core JSON-RPC server started")
    try:
        server.serve()
    finally:
        logger.info("Skald core JSON-RPC server stopping")
        sys.stdout = real_stdout
        close_managed_logging()
    return 0
