"""Alert webhook body per chat format (Д-§9.3, Д-§14.3)."""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from quack.config import Settings
from quack.ops.notify import alert_payload, post_alert


def settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_slack_is_the_default_and_sends_text():
    assert alert_payload(settings(), "boom") == {"text": "boom"}


def test_discord_sends_content():
    assert alert_payload(settings(alert_webhook_format="discord"), "boom") == {"content": "boom"}


def test_telegram_sends_chat_id_and_text():
    s = settings(alert_webhook_format="telegram", alert_webhook_chat_id="-100500")
    assert alert_payload(s, "boom") == {"chat_id": "-100500", "text": "boom"}


def test_telegram_without_chat_id_is_refused():
    with pytest.raises(ValueError, match="ALERT_WEBHOOK_CHAT_ID"):
        alert_payload(settings(alert_webhook_format="telegram"), "boom")


async def test_post_alert_without_url_sends_nothing(monkeypatch: pytest.MonkeyPatch):
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("no request expected")

    monkeypatch.setattr(httpx.AsyncClient, "post", boom)
    await post_alert(settings(), "boom")


async def test_post_alert_posts_the_payload(monkeypatch: pytest.MonkeyPatch):
    sent: list[tuple[str, object]] = []

    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: object) -> httpx.Response:
        sent.append((url, kwargs["json"]))
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    await post_alert(
        settings(
            alert_webhook_url=SecretStr("https://chat.example/hook"), alert_webhook_format="discord"
        ),
        "boom",
    )
    assert sent == [("https://chat.example/hook", {"content": "boom"})]
