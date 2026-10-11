# rest-api-toolkit

A small, tested Python toolkit for practising how real REST APIs fail, and how to deal with it. Built as a hands-on practice project for support and technical account management work.

It is not production software. It is a compact place to learn, show and test the behaviour that matters when an integration breaks.

## What is in it

| Part | What it shows |
|---|---|
| `src/apikit/client.py` | HTTP client with auth headers, timeouts, retries with exponential backoff and jitter, `Retry-After` handling, safe-retry rules for POST, request ids, Link-header and page-number pagination |
| `src/apikit/errors.py` | Typed errors for 400, 401, 403, 404, 409, 429 and 5xx, each carrying status, request id and URL |
| `src/apikit/webhook.py` | FastAPI webhook receiver: HMAC-SHA256 signature check on the raw body, constant-time compare, replay protection by timestamp, duplicate event handling |
| `examples/export_github_repos.py` | Real use: export a GitHub user's repos to CSV, with pagination and rate-limit handling |
| `postman/` | Postman collection against the Elasticsearch REST API, including requests that fail on purpose (400, 401, 404) for debugging practice |
| `docs/debugging-playbook.md` | The order I use to debug a failing API call, with a status code table |
| `docs/interview-notes.md` | Plain-English answers to common API questions, and what I do and do not claim |
| `tests/` | 27 tests, all offline (mocked transport), covering the failure cases below |

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
```

Use the client:

```python
from apikit import ApiClient, RateLimitError

with ApiClient("https://api.github.com", token=None) as client:
    for repo in client.paginate_link_header("/users/octocat/repos", params={"per_page": 100}):
        print(repo["name"])
```

Export repos to CSV (unauthenticated GitHub allows 60 requests an hour; set `GITHUB_TOKEN` for more):

```bash
python examples/export_github_repos.py octocat --out repos.csv
```

Run the webhook receiver and send it a signed event:

```bash
WEBHOOK_SECRET=dev-secret uvicorn --app-dir examples run_webhook_server:app --port 8000
# in another terminal
python examples/send_test_event.py     # run it twice to see the duplicate handled
```

## Failure cases covered by tests

- 429 with `Retry-After`: waits the stated time, then succeeds. When retries run out, the error carries `retry_after`.
- 503 and 502 then recovery: retries with growing delay, gives up after the maximum attempts.
- 400, 401, 403, 404, 409, 422: raised as typed errors and never retried.
- POST without an idempotency key is not retried. With a key, it is retried and the same key is reused.
- Network errors: retried for safe requests, then raised.
- Pagination: follows `rel="next"` until done, stops on a short page, and has a page cap as a safety stop.
- Webhooks: wrong secret, tampered body, old timestamp (replay), missing headers, duplicate event id, payload without an id.

## Limits, stated plainly

- The webhook header names and signing format are this project's own. Real providers (Stripe, GitHub, Slack) differ. Check their documentation.
- The processed-event set is in memory. A real receiver would use a database or Redis.
- OAuth2 flows and mTLS are not implemented here. Only bearer tokens and API keys are.
- The Postman collection has not been run in CI. It needs an Elasticsearch cluster.

## Licence

MIT
