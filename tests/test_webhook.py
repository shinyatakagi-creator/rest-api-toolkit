import json
import time

import pytest
from fastapi.testclient import TestClient

from apikit.webhook import create_app, sign, verify

SECRET = "test-secret-0123456789"


def send(client, event, *, secret=SECRET, ts=None, signature=None):
    body = json.dumps(event).encode()
    ts = ts or str(int(time.time()))
    sig = signature if signature is not None else sign(secret, ts, body)
    return client.post("/webhook", content=body, headers={"X-Timestamp": ts, "X-Signature": sig})


def test_valid_event_is_accepted_and_handled():
    got = []
    client = TestClient(create_app(SECRET, handler=got.append))
    resp = send(client, {"id": "evt_1", "type": "invoice.paid"})
    assert resp.status_code == 200 and resp.json()["status"] == "ok"
    assert got == [{"id": "evt_1", "type": "invoice.paid"}]


def test_wrong_secret_is_rejected():
    client = TestClient(create_app(SECRET))
    assert send(client, {"id": "evt_1"}, secret="other-secret-0123456789").status_code == 401


def test_tampered_body_is_rejected():
    client = TestClient(create_app(SECRET))
    ts = str(int(time.time()))
    sig = sign(SECRET, ts, b'{"id": "evt_1", "amount": 1}')
    resp = client.post("/webhook", content=b'{"id": "evt_1", "amount": 9999}',
                       headers={"X-Timestamp": ts, "X-Signature": sig})
    assert resp.status_code == 401


def test_old_timestamp_is_rejected_as_replay():
    client = TestClient(create_app(SECRET))
    old = str(int(time.time()) - 3600)
    assert send(client, {"id": "evt_1"}, ts=old).status_code == 401


def test_missing_headers_rejected():
    client = TestClient(create_app(SECRET))
    assert client.post("/webhook", content=b"{}").status_code == 401


def test_duplicate_event_acknowledged_but_handled_once():
    got = []
    client = TestClient(create_app(SECRET, handler=got.append))
    first = send(client, {"id": "evt_7"})
    second = send(client, {"id": "evt_7"})
    assert first.json()["status"] == "ok"
    assert second.status_code == 200 and second.json()["status"] == "duplicate"
    assert len(got) == 1


def test_payload_without_id_is_400_not_500():
    client = TestClient(create_app(SECRET))
    assert send(client, {"type": "no id"}).status_code == 400


def test_verify_unit_bad_timestamp():
    with pytest.raises(ValueError, match="bad timestamp"):
        verify(SECRET, "abc", b"{}", "x")


# ---- security regression tests ------------------------------------------------

def raw_post(client, body: bytes, *, ts=None, signature=None, secret=SECRET):
    ts = ts or str(int(time.time()))
    sig = signature if signature is not None else sign(secret, ts, body)
    return client.post("/webhook", content=body, headers={"X-Timestamp": ts, "X-Signature": sig})


@pytest.mark.parametrize("secret", ["", "short", "x" * 15])
def test_short_or_empty_secret_is_refused(secret):
    with pytest.raises(ValueError, match="at least 16"):
        create_app(secret)


def test_non_ascii_signature_is_401_not_500():
    client = TestClient(create_app(SECRET))
    ts = str(int(time.time()))
    resp = client.post("/webhook", content=b'{"id": "e"}',
                       headers={"X-Timestamp": ts, "X-Signature": "café".encode("utf-8")})
    assert resp.status_code == 401


def test_non_ascii_digit_timestamp_is_rejected():
    with pytest.raises(ValueError, match="bad timestamp"):
        verify(SECRET, "\u0661\u0662\u0663", b"{}", "00")


@pytest.mark.parametrize("event", [{"id": [1]}, {"id": {"a": 1}}, {"id": 5}, {"id": ""}, {"id": "x" * 300}, [1, 2], "text"])
def test_bad_event_id_or_shape_is_400_not_500(event):
    client = TestClient(create_app(SECRET))
    assert send(client, event).status_code == 400


def test_invalid_json_is_400():
    client = TestClient(create_app(SECRET))
    assert raw_post(client, b"{not json").status_code == 400


def test_oversized_body_is_413():
    client = TestClient(create_app(SECRET, max_body_bytes=1024))
    assert raw_post(client, b'{"id": "e", "pad": "' + b"a" * 5000 + b'"}').status_code == 413


def test_401_does_not_reveal_the_reason():
    client = TestClient(create_app(SECRET))
    bad_sig = send(client, {"id": "e1"}, secret="other-secret-0123456789")
    old_ts = send(client, {"id": "e2"}, ts=str(int(time.time()) - 3600))
    missing = client.post("/webhook", content=b"{}")
    assert bad_sig.json() == old_ts.json() == missing.json()
    assert "mismatch" not in bad_sig.text and "expired" not in old_ts.text


def test_docs_and_openapi_are_not_exposed():
    client = TestClient(create_app(SECRET))
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_failed_handler_does_not_mark_event_processed():
    calls = []

    def flaky(event):
        calls.append(event["id"])
        if len(calls) == 1:
            raise RuntimeError("boom")

    client = TestClient(create_app(SECRET, handler=flaky), raise_server_exceptions=False)
    assert send(client, {"id": "evt_9"}).status_code == 500
    retry = send(client, {"id": "evt_9"})
    assert retry.status_code == 200 and retry.json()["status"] == "ok"
    assert calls == ["evt_9", "evt_9"]


def test_remembered_events_are_bounded():
    got = []
    client = TestClient(create_app(SECRET, handler=got.append, max_remembered_events=3))
    for i in range(5):
        assert send(client, {"id": f"e{i}"}).json()["status"] == "ok"
    # e0 was evicted, so it is handled again. e4 is still remembered.
    assert send(client, {"id": "e4"}).json()["status"] == "duplicate"
    assert send(client, {"id": "e0"}).json()["status"] == "ok"
