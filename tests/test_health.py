import logging

import pytest

from agentic import health


class _FakeDb:
    def close(self):
        pass


@pytest.fixture
def notifications(monkeypatch):
    sent = []

    async def fake_notify(message, level):
        sent.append((message, level))

    monkeypatch.setattr(health, "SessionLocal", lambda: _FakeDb())
    monkeypatch.setattr(health, "_notify", fake_notify)
    return sent


def _stub_failure_repo(monkeypatch, *, streak, claim=True):
    monkeypatch.setattr(health.repository, "record_specialist_failure", lambda db, specialist, symbol, error: streak)
    monkeypatch.setattr(health.repository, "claim_specialist_alert", lambda db, specialist, threshold: claim)


async def test_failure_below_threshold_does_not_alert(monkeypatch, notifications):
    _stub_failure_repo(monkeypatch, streak=health.FAILURE_ALERT_THRESHOLD - 1)
    await health.record_failure("valuation", "AAPL", "boom")
    assert notifications == []


async def test_failure_reaching_threshold_alerts_with_context(monkeypatch, notifications):
    _stub_failure_repo(monkeypatch, streak=health.FAILURE_ALERT_THRESHOLD)
    await health.record_failure("valuation", "AAPL", "RuntimeError: API key expired")
    [(message, level)] = notifications
    assert level == logging.ERROR
    assert "valuation" in message and "AAPL" in message and "API key expired" in message
    assert f"{health.FAILURE_ALERT_THRESHOLD} runs in a row" in message


async def test_failure_alert_skipped_when_another_caller_already_claimed_it(monkeypatch, notifications):
    _stub_failure_repo(monkeypatch, streak=health.FAILURE_ALERT_THRESHOLD + 2, claim=False)
    await health.record_failure("valuation", "AAPL", "boom")
    assert notifications == []


async def test_long_error_is_truncated(monkeypatch, notifications):
    _stub_failure_repo(monkeypatch, streak=health.FAILURE_ALERT_THRESHOLD)
    await health.record_failure("valuation", "AAPL", "x" * 5000)
    [(message, _)] = notifications
    assert len(message) < 500


async def test_success_ending_alerted_streak_announces_recovery(monkeypatch, notifications):
    monkeypatch.setattr(health.repository, "record_specialist_success", lambda db, specialist: True)
    await health.record_success("valuation")
    [(message, level)] = notifications
    assert level == logging.INFO and "recovered" in message


async def test_success_without_alerted_streak_is_silent(monkeypatch, notifications):
    monkeypatch.setattr(health.repository, "record_specialist_success", lambda db, specialist: False)
    await health.record_success("valuation")
    assert notifications == []


async def test_recording_never_raises_when_database_is_down(monkeypatch, notifications):
    def db_down(*args):
        raise RuntimeError("mysql gone")

    monkeypatch.setattr(health.repository, "record_specialist_failure", db_down)
    monkeypatch.setattr(health.repository, "record_specialist_success", db_down)
    await health.record_failure("valuation", "AAPL", "boom")
    await health.record_success("valuation")
    assert notifications == []


async def test_notify_posts_text_payload_to_webhook(monkeypatch):
    posted = []

    class _Response:
        def raise_for_status(self):
            pass

    def fake_post(url, json, timeout):
        posted.append((url, json))
        return _Response()

    monkeypatch.setattr(health.settings, "alert_webhook_url", "http://hook.example/x")
    monkeypatch.setattr(health.httpx, "post", fake_post)
    await health._notify("something failed", logging.ERROR)
    assert posted == [("http://hook.example/x", {"text": "something failed"})]


async def test_notify_without_webhook_url_does_not_post(monkeypatch):
    monkeypatch.setattr(health.settings, "alert_webhook_url", "")
    monkeypatch.setattr(health.httpx, "post", lambda *a, **k: pytest.fail("should not post"))
    await health._notify("something failed", logging.ERROR)


async def test_notify_swallows_webhook_delivery_failure(monkeypatch):
    def failing_post(url, json, timeout):
        raise health.httpx.ConnectError("unreachable")

    monkeypatch.setattr(health.settings, "alert_webhook_url", "http://hook.example/x")
    monkeypatch.setattr(health.httpx, "post", failing_post)
    await health._notify("something failed", logging.ERROR)
