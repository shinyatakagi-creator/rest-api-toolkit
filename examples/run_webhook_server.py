"""Run the webhook receiver locally, then send it a signed test event.

    WEBHOOK_SECRET=dev-secret uvicorn --app-dir examples run_webhook_server:app --port 8000
    python examples/send_test_event.py
"""
import os

from apikit.webhook import create_app

app = create_app(os.environ.get("WEBHOOK_SECRET", "dev-secret"), handler=lambda e: print("received", e))
