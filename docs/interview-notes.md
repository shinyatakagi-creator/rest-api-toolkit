# Talking about this in interviews

Plain-English notes for explaining what I built and what I did not. Keep claims to what is true.

## What this is

A small practice project that I built to get hands-on with the parts of REST APIs that matter in support and technical account management: authentication, status codes, retries, rate limits, pagination, idempotency, and webhooks. It has a tested Python client, a signed-webhook receiver, and a Postman collection against the Elasticsearch REST API.

## What I can honestly say

- Elastic's product is API-driven, and I used its REST API day to day to diagnose customer cases.
- I wrote this client and receiver myself, with tests that simulate the failures real providers produce (429 with `Retry-After`, 503 then recovery, duplicate webhooks, replayed requests, tampered bodies).
- I can read a failing call from the status code, headers and request id, and explain it to a non-technical person.

## What I should not claim

- That I have built production integrations for a bank or any other customer. This is a practice project.
- Deep experience of a specific provider's SDK or OAuth flows beyond what the project covers. I have used bearer tokens and API keys. I have read about OAuth2 client credentials and mTLS but not implemented them here.

## Questions I should be ready for

1. **401 vs 403?** 401: the server does not know who you are (missing or bad credentials). 403: it knows, and you are not allowed.
2. **When is it safe to retry?** Safe methods (GET, PUT, DELETE) on 429, 502, 503, 504 and network errors. POST only with an idempotency key. Never retry 400, 401, 403 or 404 unchanged.
3. **What is idempotency and why does it matter for payments?** Repeating the same request gives the same result. Without it, a retry after a timeout can charge twice.
4. **How do you handle rate limits?** Respect `Retry-After`, back off exponentially with jitter, reduce request volume, and ask for a higher quota with usage data.
5. **A customer says the API is down. What do you do?** Reproduce with curl, check status and headers, compare with a known-good request, check the provider status page and recent changes, then collect timestamps, request ids and account id before escalating.
6. **How do webhooks go wrong?** Duplicates, out-of-order delivery, slow handlers causing timeouts and retries, and unverified signatures. Verify the signature on the raw body, check the timestamp, deduplicate by event id, acknowledge fast.
7. **What is a breaking API change?** Removing or renaming a field, changing a type, making an optional field required, or changing behaviour. Adding an optional field is normally non-breaking.
8. **Pagination styles?** Page number, offset, cursor, and Link header. Cursor is the most reliable when data changes during paging.
