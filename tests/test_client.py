import httpx
import pytest

from apikit import (ApiClient, AuthenticationError, BadRequestError, ConflictError, ForbiddenError,
                    NotFoundError, RateLimitError, RetryPolicy, ServerError)


def make_client(handler, **kw):
    sleeps: list[float] = []
    client = ApiClient("https://api.test", transport=httpx.MockTransport(handler),
                       sleep=sleeps.append, retry=kw.pop("retry", RetryPolicy(max_attempts=4, base_delay=1)), **kw)
    return client, sleeps


def test_sends_bearer_token_and_request_id():
    seen = {}

    def handler(req):
        seen.update(req.headers)
        return httpx.Response(200, json={"ok": True})

    client, _ = make_client(handler, token="abc123")
    assert client.get("/ping") == {"ok": True}
    assert seen["authorization"] == "Bearer abc123"
    assert seen["x-request-id"]


@pytest.mark.parametrize("status,exc", [
    (400, BadRequestError), (422, BadRequestError), (401, AuthenticationError), (403, ForbiddenError),
    (404, NotFoundError), (409, ConflictError),
])
def test_client_errors_map_to_types_and_are_not_retried(status, exc):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(status, text="nope", headers={"x-request-id": "req-9"})

    client, sleeps = make_client(handler)
    with pytest.raises(exc) as info:
        client.get("/thing")
    assert len(calls) == 1 and sleeps == []
    assert info.value.status == status and info.value.request_id == "req-9"


def test_retries_503_then_succeeds_with_backoff():
    responses = iter([httpx.Response(503), httpx.Response(502), httpx.Response(200, json={"n": 1})])
    client, sleeps = make_client(lambda req: next(responses))
    assert client.get("/flaky") == {"n": 1}
    assert len(sleeps) == 2
    assert sleeps[1] >= sleeps[0] / 2  # backoff grows (jitter keeps it from being exact)


def test_gives_up_after_max_attempts_and_raises_server_error():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(500)

    client, _ = make_client(handler, retry=RetryPolicy(max_attempts=3, base_delay=0.1))
    with pytest.raises(ServerError):
        client.get("/down")
    assert len(calls) == 3


def test_429_honours_retry_after():
    responses = iter([httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json={})])
    client, sleeps = make_client(lambda req: next(responses))
    client.get("/limited")
    assert sleeps == [7.0]


def test_429_exhausted_exposes_retry_after():
    client, _ = make_client(lambda req: httpx.Response(429, headers={"Retry-After": "12"}),
                            retry=RetryPolicy(max_attempts=2))
    with pytest.raises(RateLimitError) as info:
        client.get("/limited")
    assert info.value.retry_after == 12.0


def test_post_without_idempotency_key_is_not_retried():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503)

    client, _ = make_client(handler)
    with pytest.raises(ServerError):
        client.post("/payments", json={"amount": 100})
    assert len(calls) == 1  # retrying could charge twice


def test_post_with_idempotency_key_is_retried_and_key_is_reused():
    keys = []
    responses = iter([httpx.Response(503), httpx.Response(201, json={"id": "p1"})])

    def handler(req):
        keys.append(req.headers.get("idempotency-key"))
        return next(responses)

    client, _ = make_client(handler)
    assert client.post("/payments", json={"amount": 100}, idempotency_key="key-1") == {"id": "p1"}
    assert keys == ["key-1", "key-1"]


def test_network_error_retried_for_get_then_raises():
    def handler(req):
        raise httpx.ConnectError("boom")

    client, sleeps = make_client(handler, retry=RetryPolicy(max_attempts=3, base_delay=0.1))
    with pytest.raises(ServerError):
        client.get("/x")
    assert len(sleeps) == 2


def test_link_header_pagination_follows_next_until_done():
    pages = {
        "https://api.test/items?per_page=2": httpx.Response(
            200, json=[1, 2], headers={"Link": '<https://api.test/items?page=2>; rel="next"'}),
        "https://api.test/items?page=2": httpx.Response(
            200, json=[3, 4], headers={"Link": '<https://api.test/items?page=3>; rel="next"'}),
        "https://api.test/items?page=3": httpx.Response(200, json=[5]),
    }
    client, _ = make_client(lambda req: pages[str(req.url)])
    assert list(client.paginate_link_header("/items", params={"per_page": 2})) == [1, 2, 3, 4, 5]


def test_page_number_pagination_stops_on_short_page():
    data = {1: [1, 2], 2: [3, 4], 3: [5]}
    client, _ = make_client(lambda req: httpx.Response(200, json={"items": data[int(req.url.params["page"])]}))
    got = list(client.paginate_pages("/items", page_size=2, items_key="items"))
    assert got == [1, 2, 3, 4, 5]


def test_max_pages_is_a_safety_stop():
    client, _ = make_client(lambda req: httpx.Response(
        200, json=[1], headers={"Link": '<https://api.test/items?page=2>; rel="next"'}))
    assert len(list(client.paginate_link_header("/items", max_pages=3))) == 3


def test_github_style_403_with_no_quota_is_a_rate_limit_not_a_permissions_error():
    import time
    reset = str(int(time.time()) + 90)
    client, _ = make_client(lambda req: httpx.Response(
        403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": reset}), retry=RetryPolicy(max_attempts=1))
    with pytest.raises(RateLimitError) as info:
        client.get("/users/x/repos")
    assert 80 <= info.value.retry_after <= 91


def test_plain_403_is_still_forbidden():
    client, _ = make_client(lambda req: httpx.Response(403, headers={"x-ratelimit-remaining": "42"}))
    with pytest.raises(ForbiddenError):
        client.get("/admin")
