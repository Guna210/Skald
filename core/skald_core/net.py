"""HTTP helper and verified resumable file downloader."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import socket
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import requests

from skald_core import __version__
from skald_core.rpc import SkaldError

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT: float = 10.0
READ_TIMEOUT: float = 60.0
MAX_RETRIES: int = 2
BACKOFF_SECONDS: float = 1.0
DOWNLOAD_CHUNK_SIZE: int = 65536

_CONTENT_RANGE_RE = re.compile(r"^bytes\s+(\d+)-(\d+)/(\d+|\*)$", re.IGNORECASE)


class DownloadCancelled(Exception):
    """Raised when a download is cancelled via its cancel callback."""


def user_agent() -> str:
    """Return the User-Agent header value for outbound Skald HTTP requests."""
    return f"Skald/{__version__}"


def _resolve_timeout(timeout: tuple[float, float] | float | None) -> tuple[float, float] | float:
    if timeout is None:
        return (CONNECT_TIMEOUT, READ_TIMEOUT)
    return timeout


def _build_headers(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    headers = {"User-Agent": user_agent()}
    if extra:
        headers.update(extra)
    return headers


def _is_timeout_error(exc: BaseException) -> bool:
    """Return True if exc or any chained/wrapped cause is a connect or read timeout."""
    stack: list[BaseException] = [exc]
    seen: set[int] = set()
    while stack:
        cur = stack.pop()
        if id(cur) in seen:
            continue
        seen.add(id(cur))
        if isinstance(cur, (requests.exceptions.Timeout, TimeoutError, socket.timeout)):
            return True
        if cur.__cause__ is not None:
            stack.append(cur.__cause__)
        if cur.__context__ is not None:
            stack.append(cur.__context__)
        for arg in getattr(cur, "args", ()):
            if isinstance(arg, BaseException):
                stack.append(arg)
    return False


def _http_status_error(status: int, url: str, reason: str = "") -> SkaldError:
    if status == 404:
        return SkaldError(
            "http_not_found",
            f"HTTP 404 Not Found: {url}",
            details={"url": url, "status": status},
            hint="Check that the requested URL is still available.",
        )
    detail_msg = f"HTTP {status} {reason}".strip()
    return SkaldError(
        "http_error",
        f"{detail_msg}: {url}",
        details={"url": url, "status": status},
        hint="Try again later or check the server status.",
    )


def _request_exc_to_skald_error(exc: requests.exceptions.RequestException, url: str) -> SkaldError:
    if _is_timeout_error(exc):
        return SkaldError(
            "timeout",
            f"Request timed out: {url}",
            details={"url": url, "error": str(exc)},
            hint="Check your internet connection and try again.",
        )
    if isinstance(
        exc,
        (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError),
    ):
        return SkaldError(
            "offline",
            f"Network connection failed: {url}",
            details={"url": url, "error": str(exc)},
            hint="Check your internet connection or proxy settings.",
        )
    return SkaldError(
        "http_error",
        f"HTTP request failed: {url}",
        details={"url": url, "error": str(exc)},
    )


def _sleep_backoff(
    attempt: int,
    backoff: float,
    cancel: Callable[[], bool] | None = None,
) -> None:
    if cancel is not None and cancel():
        raise DownloadCancelled("Download cancelled")
    delay = backoff * (2**attempt)
    if delay > 0:
        time.sleep(delay)
    if cancel is not None and cancel():
        raise DownloadCancelled("Download cancelled")


def _check_cancel(cancel: Callable[[], bool] | None) -> None:
    if cancel is not None and cancel():
        raise DownloadCancelled("Download cancelled")


def _decode_text(resp: requests.Response) -> str:
    content_type = resp.headers.get("content-type", "")
    if (
        "charset" not in content_type.lower()
        and resp.encoding
        and resp.encoding.lower() == "iso-8859-1"
    ):
        resp.encoding = "utf-8"
    return resp.text


def _get_response_with_retries(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: tuple[float, float] | float | None = None,
    retries: int | None = None,
    backoff: float | None = None,
    session: requests.Session | None = None,
) -> requests.Response:
    max_retries = MAX_RETRIES if retries is None else retries
    backoff_base = BACKOFF_SECONDS if backoff is None else backoff
    req_timeout = _resolve_timeout(timeout)
    req_headers = _build_headers(headers)

    own_session = session is None
    sess = requests.Session() if session is None else session
    try:
        for attempt in range(max_retries + 1):
            try:
                resp = sess.get(url, headers=req_headers, timeout=req_timeout)
            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            ) as exc:
                if attempt < max_retries:
                    logger.warning(
                        "HTTP request attempt %d/%d failed for %s (%s); retrying",
                        attempt + 1,
                        max_retries + 1,
                        url,
                        exc,
                    )
                    _sleep_backoff(attempt, backoff_base)
                    continue
                raise _request_exc_to_skald_error(exc, url) from exc
            except requests.exceptions.RequestException as exc:
                raise _request_exc_to_skald_error(exc, url) from exc

            status = resp.status_code
            if 500 <= status < 600:
                reason = resp.reason or ""
                resp.close()
                if attempt < max_retries:
                    logger.warning(
                        "HTTP %d on attempt %d/%d for %s; retrying",
                        status,
                        attempt + 1,
                        max_retries + 1,
                        url,
                    )
                    _sleep_backoff(attempt, backoff_base)
                    continue
                raise _http_status_error(status, url, reason)

            if status >= 400 or status < 200:
                reason = resp.reason or ""
                resp.close()
                raise _http_status_error(status, url, reason)

            return resp
    finally:
        if own_session:
            sess.close()

    raise AssertionError("unreachable")  # pragma: no cover


def get_text(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: tuple[float, float] | float | None = None,
    retries: int | None = None,
    backoff: float | None = None,
    session: requests.Session | None = None,
) -> str:
    """Fetch a URL and return its decoded text body."""
    with _get_response_with_retries(
        url,
        headers=headers,
        timeout=timeout,
        retries=retries,
        backoff=backoff,
        session=session,
    ) as resp:
        return _decode_text(resp)


def get_json(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: tuple[float, float] | float | None = None,
    retries: int | None = None,
    backoff: float | None = None,
    session: requests.Session | None = None,
) -> Any:
    """Fetch a URL and parse its response body as JSON."""
    with _get_response_with_retries(
        url,
        headers=headers,
        timeout=timeout,
        retries=retries,
        backoff=backoff,
        session=session,
    ) as resp:
        try:
            return resp.json()
        except ValueError as exc:
            raise SkaldError(
                "http_error",
                f"Invalid JSON response from {url}",
                details={"url": url, "error": str(exc)},
            ) from exc


def _file_size_and_sha256(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as fh:
        while chunk := fh.read(DOWNLOAD_CHUNK_SIZE):
            digest.update(chunk)
            total += len(chunk)
    return total, digest.hexdigest()


def _verify_part_or_raise(
    part_path: Path,
    dest_path: Path,
    *,
    url: str,
    expected_size: int,
    expected_sha256: str,
) -> None:
    actual_size, actual_sha = _file_size_and_sha256(part_path)
    if actual_size != expected_size or actual_sha != expected_sha256:
        part_path.unlink(missing_ok=True)
        raise SkaldError(
            "checksum_mismatch",
            f"Downloaded file failed verification for {dest_path.name}",
            details={
                "url": url,
                "dest": str(dest_path),
                "expected_size": expected_size,
                "actual_size": actual_size,
                "expected_sha256": expected_sha256,
                "actual_sha256": actual_sha,
            },
            hint="Try downloading the file again.",
        )


def _parse_content_length(headers: Mapping[str, str]) -> int | None:
    raw = headers.get("Content-Length")
    if raw is None:
        return None
    try:
        value = int(raw.strip())
    except ValueError:
        return None
    return value if value >= 0 else None


def download(
    url: str,
    dest: Path | str,
    sha256: str,
    size: int,
    progress_cb: Callable[[int, int], None] | None = None,
    cancel: Callable[[], bool] | None = None,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: tuple[float, float] | float | None = None,
    retries: int | None = None,
    backoff: float | None = None,
    session: requests.Session | None = None,
) -> Path:
    """Download url to dest via dest.part, resuming with Range and verifying size/SHA-256."""
    if size < 0:
        raise ValueError(f"size must be non-negative, got {size}")

    _check_cancel(cancel)

    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = dest_path.with_name(f"{dest_path.name}.part")
    expected_sha = sha256.strip().lower()

    max_retries = MAX_RETRIES if retries is None else retries
    backoff_base = BACKOFF_SECONDS if backoff is None else backoff
    req_timeout = _resolve_timeout(timeout)

    if part_path.exists():
        existing_size = part_path.stat().st_size
        if existing_size > size:
            part_path.unlink(missing_ok=True)
        elif existing_size == size:
            _verify_part_or_raise(
                part_path,
                dest_path,
                url=url,
                expected_size=size,
                expected_sha256=expected_sha,
            )
            if progress_cb is not None:
                progress_cb(size, size)
            os.replace(part_path, dest_path)
            return dest_path

    restarted_from_zero = False
    attempt = 0
    own_session = session is None
    sess = requests.Session() if session is None else session
    try:
        while True:
            _check_cancel(cancel)

            existing_size = part_path.stat().st_size if part_path.exists() else 0
            if existing_size > size:
                part_path.unlink(missing_ok=True)
                existing_size = 0
            elif existing_size == size and part_path.exists():
                break

            req_headers = _build_headers(headers)
            sent_range = existing_size > 0
            if sent_range:
                req_headers["Range"] = f"bytes={existing_size}-"

            try:
                with sess.get(url, headers=req_headers, timeout=req_timeout, stream=True) as resp:
                    status = resp.status_code
                    if 500 <= status < 600:
                        reason = resp.reason or ""
                        if attempt < max_retries:
                            logger.warning(
                                "HTTP %d on download attempt %d/%d for %s; retrying",
                                status,
                                attempt + 1,
                                max_retries + 1,
                                url,
                            )
                            _sleep_backoff(attempt, backoff_base, cancel)
                            attempt += 1
                            continue
                        raise _http_status_error(status, url, reason)

                    if status == 416 and sent_range and not restarted_from_zero:
                        logger.warning(
                            "HTTP 416 on Range resume for %s; restarting from zero",
                            url,
                        )
                        restarted_from_zero = True
                        part_path.unlink(missing_ok=True)
                        continue

                    if status >= 400 or status < 200:
                        raise _http_status_error(status, url, resp.reason or "")

                    if sent_range and status == 206:
                        content_range = resp.headers.get("Content-Range")
                        if content_range:
                            match = _CONTENT_RANGE_RE.match(content_range.strip())
                            if not match:
                                raise SkaldError(
                                    "http_error",
                                    f"Unexpected Content-Range {content_range!r} from {url}",
                                    details={
                                        "url": url,
                                        "expected_offset": existing_size,
                                        "content_range": content_range,
                                    },
                                )
                            range_start = int(match.group(1))
                            range_total = match.group(3)
                            if range_start != existing_size:
                                if not restarted_from_zero:
                                    logger.warning(
                                        "Content-Range start %d != .part size %d for %s; "
                                        "restarting from zero",
                                        range_start,
                                        existing_size,
                                        url,
                                    )
                                    restarted_from_zero = True
                                    part_path.unlink(missing_ok=True)
                                    continue
                                raise SkaldError(
                                    "http_error",
                                    f"Unexpected Content-Range {content_range!r} from {url}",
                                    details={
                                        "url": url,
                                        "expected_offset": existing_size,
                                        "content_range": content_range,
                                    },
                                )
                            if range_total != "*" and int(range_total) != size:
                                part_path.unlink(missing_ok=True)
                                raise SkaldError(
                                    "checksum_mismatch",
                                    f"Content-Range total {range_total} does not match "
                                    f"expected size {size} for {dest_path.name}",
                                    details={
                                        "url": url,
                                        "dest": str(dest_path),
                                        "expected_size": size,
                                        "actual_size": int(range_total),
                                    },
                                    hint="Try downloading the file again.",
                                )
                        mode = "ab"
                        bytes_written = existing_size
                    else:
                        content_length = _parse_content_length(resp.headers)
                        if content_length is not None and content_length > size:
                            part_path.unlink(missing_ok=True)
                            raise SkaldError(
                                "checksum_mismatch",
                                f"Content-Length {content_length} exceeds expected size {size} "
                                f"for {dest_path.name}",
                                details={
                                    "url": url,
                                    "dest": str(dest_path),
                                    "expected_size": size,
                                    "actual_size": content_length,
                                },
                                hint="Try downloading the file again.",
                            )
                        mode = "wb"
                        bytes_written = 0

                    oversize_actual: int | None = None
                    with part_path.open(mode) as fh:
                        for chunk in resp.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                            _check_cancel(cancel)
                            if not chunk:
                                continue
                            if bytes_written + len(chunk) > size:
                                oversize_actual = bytes_written + len(chunk)
                                break
                            fh.write(chunk)
                            fh.flush()
                            bytes_written += len(chunk)
                            if progress_cb is not None:
                                progress_cb(bytes_written, size)
                            _check_cancel(cancel)

                    if oversize_actual is not None:
                        part_path.unlink(missing_ok=True)
                        raise SkaldError(
                            "checksum_mismatch",
                            f"Downloaded bytes exceeded expected size {size} for {dest_path.name}",
                            details={
                                "url": url,
                                "dest": str(dest_path),
                                "expected_size": size,
                                "actual_size": oversize_actual,
                            },
                            hint="Try downloading the file again.",
                        )

                break
            except DownloadCancelled:
                raise
            except SkaldError:
                raise
            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            ) as exc:
                if attempt < max_retries:
                    logger.warning(
                        "Download attempt %d/%d failed for %s (%s); retrying",
                        attempt + 1,
                        max_retries + 1,
                        url,
                        exc,
                    )
                    _sleep_backoff(attempt, backoff_base, cancel)
                    attempt += 1
                    continue
                raise _request_exc_to_skald_error(exc, url) from exc
            except requests.exceptions.RequestException as exc:
                raise _request_exc_to_skald_error(exc, url) from exc
    finally:
        if own_session:
            sess.close()

    _check_cancel(cancel)
    _verify_part_or_raise(
        part_path,
        dest_path,
        url=url,
        expected_size=size,
        expected_sha256=expected_sha,
    )
    os.replace(part_path, dest_path)
    return dest_path
