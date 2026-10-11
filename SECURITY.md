# Security

This is a learning and portfolio project, not a supported product. I still want to hear about problems.

## Reporting

Please use GitHub's private vulnerability reporting (Security tab, "Report a vulnerability") rather than a public issue.
I will aim to reply within a week.

## What the code defends against

- Credentials sent over plain HTTP, to another host via a pagination link, or via a redirect.
- API keys appearing in logs and error messages.
- Webhook forgery and replay (HMAC signature, timestamp window), oversized bodies, malformed events, and unbounded memory use.
- CSV formula injection in the export example.

## Known limits

- Webhook de-duplication is in memory only (capped, lost on restart).
- No rate limiting, OAuth2 or mTLS.
- The signing format is this project's own, not any provider's.
