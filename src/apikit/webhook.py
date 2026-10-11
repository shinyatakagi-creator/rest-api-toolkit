"""A webhook receiver that does the things providers expect, with basic abuse limits.

1. Verify the signature (HMAC-SHA256 over timestamp + body) with a constant-time compare.
2. Reject old timestamps, so a captured request cannot be replayed later.
3. Acknowledge fast and ignore duplicates. Providers retry, so the same event id can arrive twice.
4. Limit the body size, validate the event shape, and never echo the reason a check failed.

Header names here are this project's own convention. Real providers differ
(Stripe, GitHub and Slack all sign slightly differently), so check their docs.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from collections import OrderedDict

from fastapi import FastAPI, Header, HTTPException, Request

log = logging.getLogger("apikit.webhook")

SIGNATURE_HEADER = "X-Signature"
TIMESTAMP_HEADER = "X-Timestamp"
TOLERANCE_SECONDS = 300
MIN_SECRET_LENGTH = 16
MAX_BODY_BYTES = 1_048_576  # 1 MiB
MAX_EVENT_ID_LENGTH = 256
MAX_REMEMBERED_EVENTS = 10_000


def sign(secret: str, timestamp: str, body: bytes) -> str:
    """Return the hex signature for a payload. Senders use this; receivers recompute it."""
    message = timestamp.encode() + b"." + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify(secret: str, timestamp: str, body: bytes, signature: str, *, now: float | None = None,
           tolerance: int = TOLERANCE_SECONDS) -> None:
    """Raise ValueError with a reason if the request should be rejected."""
    # ASCII digits only. int() would also accept other scripts' digits and surrounding spaces.
    if not isinstance(timestamp, str) or not (timestamp.isascii() and timestamp.isdigit()) or len(timestamp) > 12:
        raise ValueError("bad timestamp")
    if abs((now if now is not None else time.time()) - int(timestamp)) > tolerance:
        raise ValueError("timestamp outside tolerance")
    expected = sign(secret, timestamp, body).encode()
    # Compare bytes: compare_digest raises TypeError on non-ASCII str, which would become a 500.
    provided = (signature or "").encode("utf-8", "replace")
    if not hmac.compare_digest(expected, provided):  # constant-time, avoids timing leaks
        raise ValueError("signature mismatch")


class _RecentIds:
    """Remembers the most recent event ids with a hard size cap, so memory cannot grow forever.

    Trade-off: an id older than the cap can be accepted again. A real receiver would use a
    database or Redis with a unique constraint and an expiry.
    """

    def __init__(self, max_entries: int = MAX_REMEMBERED_EVENTS) -> None:
        self._ids: OrderedDict[str, None] = OrderedDict()
        self._max = max_entries

    def __contains__(self, event_id: str) -> bool:
        return event_id in self._ids

    def add(self, event_id: str) -> None:
        self._ids[event_id] = None
        self._ids.move_to_end(event_id)
        while len(self._ids) > self._max:
            self._ids.popitem(last=False)

    def __len__(self) -> int:
        return len(self._ids)


async def _read_limited(request: Request, limit: int) -> bytes:
    """Read the body but stop as soon as it exceeds the limit (also covers chunked uploads)."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail="payload too large")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(status_code=413, detail="payload too large")
        chunks.append(chunk)
    return b"".join(chunks)


def create_app(secret: str, *, handler=None, max_body_bytes: int = MAX_BODY_BYTES,
               max_remembered_events: int = MAX_REMEMBERED_EVENTS) -> FastAPI:
    if not isinstance(secret, str) or len(secret) < MIN_SECRET_LENGTH:
        raise ValueError(
            f"Webhook secret must be at least {MIN_SECRET_LENGTH} characters. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    app = FastAPI(title="Webhook receiver", docs_url=None, redoc_url=None, openapi_url=None)
    processed = _RecentIds(max_remembered_events)
    app.state.processed = processed

    @app.post("/webhook")
    async def receive(
        request: Request,
        x_signature: str = Header(default=""),
        x_timestamp: str = Header(default=""),
    ):
        body = await _read_limited(request, max_body_bytes)  # raw bytes: sign what was sent
        try:
            verify(secret, x_timestamp, body, x_signature)
        except ValueError as exc:
            log.warning("webhook rejected: %s", exc)  # the reason goes to the log, not to the caller
            raise HTTPException(status_code=401, detail="invalid signature")

        try:
            event = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
            raise HTTPException(status_code=400, detail="payload must be a JSON object")
        event_id = event.get("id") if isinstance(event, dict) else None
        if not isinstance(event_id, str) or not event_id or len(event_id) > MAX_EVENT_ID_LENGTH:
            raise HTTPException(status_code=400, detail="payload must be a JSON object with a string id")

        if event_id in processed:
            return {"status": "duplicate", "id": event_id}  # still 200, so the sender stops retrying
        if handler:
            try:
                handler(event)
            except Exception:
                log.exception("handler failed for event %s", event_id)
                # Not marked as processed, so the sender's retry gets another go.
                raise HTTPException(status_code=500, detail="handler error")
        processed.add(event_id)
        return {"status": "ok", "id": event_id}

    return app
