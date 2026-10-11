"""Run the webhook receiver locally, then send it a signed test event.

    export WEBHOOK_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
    uvicorn --app-dir examples run_webhook_server:app --host 127.0.0.1 --port 8000
    python examples/send_test_event.py        # in a second terminal with the same WEBHOOK_SECRET

The server binds to localhost only. There is no default secret on purpose.
"""
import os

from apikit.webhook import create_app

secret = os.environ.get("WEBHOOK_SECRET")
if not secret:
    raise SystemExit("Set WEBHOOK_SECRET first (at least 16 characters).")

app = create_app(secret, handler=lambda e: print("received event", e.get("id")))
