"""A webhook receiver that does the three things providers expect.

1. Verify the signature (HMAC-SHA256 over timestamp + body) with a constant-time compare.
2. Reject old timestamps, so a captured request cannot be replayed later.
3. Acknowledge fast and ignore duplicates. Providers retry, so the same event id can arrive twice.

Header names here are this project's own convention. Real providers differ
(Stripe, GitHub and Slack all sign slightly differently), so check their docs.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time

from fastapi import FastAPI, Header, HTTPException, Request

SIGNATURE_HEADER = "X-Signature"
TIMESTAMP_HEADER = "X-Timestamp"
TOLERANCE_SECONDS = 300


def sign(secret: str, timestamp: str, body: bytes) -> str:
    """Return the hex signature for a payload. Senders use this; receivers recompute it."""
    message = timestamp.encode() + b"." + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify(secret: str, timestamp: str, body: bytes, signature: str, *, now: float | None = None,
           tolerance: int = TOLERANCE_SECONDS) -> None:
    """Raise ValueError with a reason if the request should be rejected."""
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        raise ValueError("bad timestamp")
    if abs((now if now is not None else time.time()) - ts) > tolerance:
        raise ValueError("timestamp outside tolerance")
    expected = sign(secret, timestamp, body)
    if not hmac.compare_digest(expected, signature or ""):  # constant-time, avoids timing leaks
        raise ValueError("signature mismatch")


def create_app(secret: str, *, handler=None, seen: set[str] | None = None) -> FastAPI:
    app = FastAPI(title="Webhook receiver")
    processed: set[str] = seen if seen is not None else set()  # use Redis or a database in real life
    app.state.processed = processed

    @app.post("/webhook")
    async def receive(
        request: Request,
        x_signature: str = Header(default=""),
        x_timestamp: str = Header(default=""),
    ):
        body = await request.body()  # raw bytes: sign what was sent, not re-serialised JSON
        try:
            verify(secret, x_timestamp, body, x_signature)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc))

        try:
            event = json.loads(body)
            event_id = event["id"]
        except (json.JSONDecodeError, KeyError, TypeError):
            raise HTTPException(status_code=400, detail="payload must be JSON with an id")

        if event_id in processed:
            return {"status": "duplicate", "id": event_id}  # still 200, so the sender stops retrying
        processed.add(event_id)
        if handler:
            handler(event)
        return {"status": "ok", "id": event_id}

    return app
