"""Send a correctly signed event to the local receiver. Run it twice to see duplicate handling."""
import json
import os
import time
import uuid

import httpx

from apikit.webhook import sign

secret = os.environ.get("WEBHOOK_SECRET")
if not secret:
    raise SystemExit("Set WEBHOOK_SECRET to the same value the server uses.")
body = json.dumps({"id": os.environ.get("EVENT_ID", str(uuid.uuid4())), "type": "invoice.paid"}).encode()
ts = str(int(time.time()))
resp = httpx.post("http://127.0.0.1:8000/webhook", content=body,
                  headers={"X-Timestamp": ts, "X-Signature": sign(secret, ts, body),
                           "Content-Type": "application/json"})
print(resp.status_code, resp.json())
