"""A small REST client that handles the things that go wrong in real integrations.

Covers: auth headers, timeouts, retries with exponential backoff and jitter,
Retry-After on 429, retry only when it is safe, pagination (Link header and
page-number styles), request ids, and typed errors.
"""
from __future__ import annotations

import logging
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

import httpx

from .errors import (
    ApiError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    ServerError,
)

log = logging.getLogger("apikit")

# Methods that are safe to repeat. POST is only retried when an idempotency key is sent.
IDEMPOTENT_METHODS = {"GET", "HEAD", "OPTIONS", "PUT", "DELETE"}


@dataclass
class RetryPolicy:
    max_attempts: int = 4
    base_delay: float = 0.5
    max_delay: float = 30.0
    retry_statuses: frozenset[int] = field(default_factory=lambda: frozenset({429, 500, 502, 503, 504}))

    def delay_for(self, attempt: int, retry_after: float | None) -> float:
        """Seconds to wait before the next attempt. Attempt 1 is the first retry."""
        if retry_after is not None:
            return min(retry_after, self.max_delay)
        exp = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
        return exp / 2 + random.uniform(0, exp / 2)  # jitter, so clients do not retry in lockstep


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None  # an HTTP-date form exists; ignored here to keep this simple


def _raise_for_status(resp: httpx.Response, request_id: str) -> None:
    if resp.status_code < 400:
        return
    rid = resp.headers.get("x-request-id") or resp.headers.get("x-correlation-id") or request_id
    kwargs = dict(status=resp.status_code, body=resp.text[:500], request_id=rid, url=str(resp.request.url))
    code = resp.status_code
    # GitHub signals an exhausted primary rate limit with 403 plus x-ratelimit-remaining: 0, not 429.
    if code == 403 and resp.headers.get("x-ratelimit-remaining") == "0":
        reset = resp.headers.get("x-ratelimit-reset")
        wait = max(0.0, float(reset) - time.time()) if reset and reset.isdigit() else _parse_retry_after(resp.headers.get("retry-after"))
        raise RateLimitError("Rate limited (403 with no quota remaining)", retry_after=wait, **kwargs)
    if code == 429:
        raise RateLimitError("Rate limited", retry_after=_parse_retry_after(resp.headers.get("retry-after")), **kwargs)
    if code == 401:
        raise AuthenticationError("Authentication failed", **kwargs)
    if code == 403:
        raise ForbiddenError("Forbidden", **kwargs)
    if code == 404:
        raise NotFoundError("Not found", **kwargs)
    if code == 409:
        raise ConflictError("Conflict", **kwargs)
    if code in (400, 422):
        raise BadRequestError("Bad request", **kwargs)
    if code >= 500:
        raise ServerError("Server error", **kwargs)
    raise ApiError("Unexpected response", **kwargs)


class ApiClient:
    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        api_key: str | None = None,
        api_key_header: str = "X-API-Key",
        timeout: float = 10.0,
        retry: RetryPolicy | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        headers = {"Accept": "application/json", "User-Agent": "rest-api-toolkit/0.1"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if api_key:
            headers[api_key_header] = api_key
        headers.update(default_headers or {})
        self._http = httpx.Client(base_url=base_url, headers=headers, timeout=timeout, transport=transport)
        self.retry = retry or RetryPolicy()
        self._sleep = sleep
        self.last_response: httpx.Response | None = None

    # ---- lifecycle -------------------------------------------------
    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "ApiClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- core request ----------------------------------------------
    def request(self, method: str, path: str, *, idempotency_key: str | None = None, **kwargs: Any) -> httpx.Response:
        method = method.upper()
        request_id = str(uuid.uuid4())
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("X-Request-ID", request_id)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        safe_to_retry = method in IDEMPOTENT_METHODS or bool(idempotency_key)

        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self._http.request(method, path, headers=headers, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if safe_to_retry and attempt < self.retry.max_attempts:
                    delay = self.retry.delay_for(attempt, None)
                    log.warning("%s %s failed (%s). Retry %d in %.1fs. request_id=%s",
                                method, path, type(exc).__name__, attempt, delay, request_id)
                    self._sleep(delay)
                    continue
                raise ServerError(f"Network failure: {type(exc).__name__}", request_id=request_id, url=path) from exc

            self.last_response = resp
            if (resp.status_code in self.retry.retry_statuses and safe_to_retry
                    and attempt < self.retry.max_attempts):
                delay = self.retry.delay_for(attempt, _parse_retry_after(resp.headers.get("retry-after")))
                log.warning("%s %s returned %d. Retry %d in %.1fs. request_id=%s",
                            method, path, resp.status_code, attempt, delay, request_id)
                self._sleep(delay)
                continue

            log.debug("%s %s -> %d (attempts=%d, request_id=%s)", method, path, resp.status_code, attempt, request_id)
            _raise_for_status(resp, request_id)
            return resp

    # ---- convenience verbs -----------------------------------------
    def get(self, path: str, **kw: Any) -> Any:
        return self.request("GET", path, **kw).json()

    def post(self, path: str, json: Any = None, **kw: Any) -> Any:
        resp = self.request("POST", path, json=json, **kw)
        return resp.json() if resp.content else None

    def put(self, path: str, json: Any = None, **kw: Any) -> Any:
        resp = self.request("PUT", path, json=json, **kw)
        return resp.json() if resp.content else None

    def delete(self, path: str, **kw: Any) -> None:
        self.request("DELETE", path, **kw)

    # ---- pagination ------------------------------------------------
    def paginate_link_header(self, path: str, *, params: dict | None = None, max_pages: int = 100) -> Iterator[Any]:
        """Follow rel="next" in the Link header (GitHub style). Yields items."""
        url: str | None = path
        query = dict(params or {})
        for _ in range(max_pages):
            resp = self.request("GET", url, params=query if url == path else None)
            data = resp.json()
            yield from (data if isinstance(data, list) else [data])
            url = resp.links.get("next", {}).get("url")
            if not url:
                return

    def paginate_pages(self, path: str, *, params: dict | None = None, page_param: str = "page",
                       size_param: str = "per_page", page_size: int = 50, items_key: str | None = None,
                       max_pages: int = 100) -> Iterator[Any]:
        """Page-number style. Stops on an empty page or a short page."""
        for page in range(1, max_pages + 1):
            query = {**(params or {}), page_param: page, size_param: page_size}
            data = self.get(path, params=query)
            items = data[items_key] if items_key else data
            if not items:
                return
            yield from items
            if len(items) < page_size:
                return
