from __future__ import annotations

import requests

from alerting.webhook import send_webhook


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def test_send_webhook_success(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append((url, json))
        return _FakeResponse(200)

    monkeypatch.setattr(requests, "post", fake_post)
    ok = send_webhook("https://example.com/hook", {"foo": "bar"})
    assert ok is True
    assert calls == [("https://example.com/hook", {"foo": "bar"})]


def test_send_webhook_retries_then_succeeds(monkeypatch):
    attempts = {"n": 0}

    def flaky_post(url, json, timeout):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise requests.ConnectionError("boom")
        return _FakeResponse(200)

    monkeypatch.setattr(requests, "post", flaky_post)
    monkeypatch.setattr("alerting.webhook.time.sleep", lambda _s: None)
    ok = send_webhook("https://example.com/hook", {}, retries=2)
    assert ok is True
    assert attempts["n"] == 2


def test_send_webhook_gives_up_after_retries_exhausted(monkeypatch):
    def always_fails(url, json, timeout):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(requests, "post", always_fails)
    monkeypatch.setattr("alerting.webhook.time.sleep", lambda _s: None)
    ok = send_webhook("https://example.com/hook", {}, retries=1)
    assert ok is False
