import json
import time

import pytest
from fastapi.testclient import TestClient

from apikit.webhook import create_app, sign, verify

SECRET = "test-secret"


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
    assert send(client, {"id": "evt_1"}, secret="other").status_code == 401


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
