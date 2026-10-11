"""Export a GitHub user's public repos to CSV using the toolkit.

    python examples/export_github_repos.py torvalds --out repos.csv

Unauthenticated GitHub allows 60 requests an hour. Set GITHUB_TOKEN to raise that.
Shows: Link header pagination, rate limit headers, typed errors.
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import sys

from apikit import ApiClient, AuthenticationError, ForbiddenError, NotFoundError, RateLimitError

FIELDS = ["name", "language", "stargazers_count", "forks_count", "pushed_at", "html_url"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("user")
    ap.add_argument("--out", default="repos.csv")
    ap.add_argument("--max-pages", type=int, default=5)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    token = os.environ.get("GITHUB_TOKEN")
    with ApiClient("https://api.github.com", token=token,
                   default_headers={"X-GitHub-Api-Version": "2022-11-28"}) as client:
        try:
            repos = list(client.paginate_link_header(
                f"/users/{args.user}/repos", params={"per_page": 100, "sort": "pushed"}, max_pages=args.max_pages))
        except NotFoundError:
            print(f"No such user: {args.user}", file=sys.stderr)
            return 2
        except AuthenticationError:
            print("GITHUB_TOKEN was rejected (401). Is it expired or mistyped?", file=sys.stderr)
            return 2
        except ForbiddenError as exc:
            print(f"Forbidden (403). Check token scopes. Request id: {exc.request_id}", file=sys.stderr)
            return 2
        except RateLimitError as exc:
            print(f"Rate limited. Retry after {exc.retry_after}s, or set GITHUB_TOKEN.", file=sys.stderr)
            return 3
        remaining = client.last_response.headers.get("x-ratelimit-remaining") if client.last_response else None

    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(repos)
    print(f"Wrote {len(repos)} repos to {args.out}. Rate limit remaining: {remaining}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
