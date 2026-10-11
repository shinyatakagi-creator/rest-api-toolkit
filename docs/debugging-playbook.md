# API debugging playbook

How I work through a failing API call, in order. Written for support and TAM work, where the first job is finding where the problem sits.

## 1. Reproduce it with the smallest possible request

```bash
curl -sv -X GET "https://api.example.com/v1/things" \
  -H "Authorization: Bearer $TOKEN" 2>&1 | less
```

`-v` shows the request line, the headers sent, the status line and the response headers. Check these before anything else:

- Did the `Authorization` header actually go out?
- Which host and path did it hit (redirects, trailing slashes, wrong version)?
- Which response headers came back: `x-request-id`, `retry-after`, `x-ratelimit-*`, `www-authenticate`, `content-type`?

## 2. Read the status code

| Status | Meaning | First thing to check | Retry? |
|---|---|---|---|
| 400 | Request is malformed | JSON syntax, required fields, types | No, fix the request |
| 401 | Not authenticated | Token missing, expired, wrong environment | No, fix credentials (refresh once if the API supports it) |
| 403 | Authenticated but not allowed | Scopes, roles, IP allow-list | No, fix permissions |
| 404 | Not found | Path, id, API version. Some APIs return 404 to hide resources you cannot see | No |
| 409 | Conflict | Duplicate create, stale version, state mismatch | Not blindly |
| 422 | Valid JSON, invalid content | Field-level validation messages | No |
| 429 | Rate limited | `Retry-After`, quota, burst behaviour | Yes, after the delay |
| 500 | Provider bug | Request id for the provider | Maybe, then escalate |
| 502 / 503 / 504 | Gateway, overload, timeout upstream | Status page, region | Yes, with backoff |

401 means "who are you". 403 means "I know who you are, and no".

## 3. Separate "my side" from "their side"

- Same request works in `curl` but not in the app: look at headers, proxies, TLS, timeouts and client libraries.
- Works for one account, fails for another: scopes, tenant config, data.
- Fails only sometimes: rate limits, retries, race conditions, one bad node. Compare request ids.
- Used to work: check recent changes (token rotation, API version, deploys, provider incident).

## 4. Gather evidence before escalating

Collect: UTC timestamp, full request (secrets redacted), status and body, `x-request-id` or correlation id, account or tenant id, the last time it worked, and how often it fails. A support ticket with these gets fixed faster than one that says "API is down".

## 5. Explain it to a non-technical person

"Our system asked their system for the invoice list. Their system said the login we used had expired (a 401), so nothing was sent. We refreshed the login and it worked. We are adding an alert so an expiring login is caught before it breaks."

## Things that catch people out

- `_bulk` style endpoints can return 200 while individual items failed. Always check the per-item errors.
- Retrying a non-idempotent POST (payments, orders) can create duplicates. Use an idempotency key.
- Webhooks arrive more than once and out of order. Deduplicate by event id.
- Pagination: stop on an empty page, and cap the number of pages.
- Clock skew breaks signed requests, so compare timestamps.
- A 200 with an error message in the body is still a failure for your code.
