"""Low-level HTTP sender using httpx.

Does NOT retry — retry is handled by the caller (retry.py).
Each function sends a single request and either returns the result
or raises an appropriate error.
"""

from __future__ import annotations

import logging

import httpx

from discord_ops_alert.errors import DiscordOpsError, ErrorCode, RetryableError

_USER_AGENT = "discord-ops-alert-py (https://github.com/LucaPinheiro/discord-ops)"
_log = logging.getLogger("discord_ops_alert.http")


def _build_headers(extra: dict[str, str]) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "User-Agent": _USER_AGENT}
    headers.update(extra)
    return headers


def _extract_retry_after_ms(response_headers: httpx.Headers, body: dict | str) -> int | None:
    """Extract retry delay from Retry-After header or Discord JSON field, in milliseconds."""
    header_val = response_headers.get("Retry-After")
    if header_val is not None:
        try:
            return int(float(header_val) * 1000)
        except (ValueError, TypeError):
            pass
    if isinstance(body, dict):
        ra = body.get("retry_after")
        if ra is not None:
            try:
                return int(float(ra) * 1000)
            except (ValueError, TypeError):
                pass
    return None


def _handle_response(
    status: int,
    body: dict | str,
    response_headers: httpx.Headers,
) -> tuple[int, dict]:
    """Raise RetryableError on 429/5xx; return (status, body) otherwise."""
    if status == 429 or 500 <= status <= 599:
        retry_after_ms = _extract_retry_after_ms(response_headers, body)
        raise RetryableError(status_code=status, body=str(body), retry_after_ms=retry_after_ms)
    if not isinstance(body, dict):
        _log.debug("discord response body is not a dict (status=%d): %r", status, body)
        return status, {}
    return status, body


async def post_async(
    url: str,
    headers: dict[str, str],
    body: dict,
    timeout_ms: int = 5000,
) -> tuple[int, dict]:
    """Send a single POST request asynchronously. Returns (status_code, response_body).

    Raises:
        RetryableError: on 429 or 5xx so retry.py can catch and retry.
        httpx.TimeoutException: on timeout (propagates to retry layer).
        DiscordOpsError(NETWORK_ERROR): on other network errors.

    Does NOT raise on 4xx (caller decides what to do).
    """
    timeout = httpx.Timeout(timeout_ms / 1000)
    merged_headers = _build_headers(headers)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body, headers=merged_headers)
            try:
                data = resp.json()
            except Exception:
                data = {}
            return _handle_response(resp.status_code, data, resp.headers)
    except RetryableError:
        raise
    except httpx.TimeoutException:
        raise
    except httpx.HTTPError as exc:
        raise DiscordOpsError(
            ErrorCode.NETWORK_ERROR,
            f"Network error calling Discord: {exc}",
            cause=exc,
        ) from exc


def post_sync(
    url: str,
    headers: dict[str, str],
    body: dict,
    timeout_ms: int = 5000,
) -> tuple[int, dict]:
    """Synchronous version of post_async."""
    timeout = httpx.Timeout(timeout_ms / 1000)
    merged_headers = _build_headers(headers)
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=body, headers=merged_headers)
            try:
                data = resp.json()
            except Exception:
                data = {}
            return _handle_response(resp.status_code, data, resp.headers)
    except RetryableError:
        raise
    except httpx.TimeoutException:
        raise
    except httpx.HTTPError as exc:
        raise DiscordOpsError(
            ErrorCode.NETWORK_ERROR,
            f"Network error calling Discord: {exc}",
            cause=exc,
        ) from exc
