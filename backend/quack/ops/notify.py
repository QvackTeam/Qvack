"""Team chat webhook for alerts (Д-§9.3, ТЗ Фазы 4 WP9.5).

The documents do not choose the chat (Д-§14.3: "канал не выбран"), so the body shape is a setting
`alert_webhook_format`, not a constant: `slack` (also Mattermost, Rocket.Chat) sends `{"text"}`,
`discord` sends `{"content"}`, `telegram` sends `{"chat_id", "text"}` to the `sendMessage` URL.
"""

from __future__ import annotations

from typing import Any

import httpx

from quack.config import Settings

HTTP_TIMEOUT_S = 10.0


def alert_payload(settings: Settings, message: str) -> dict[str, Any]:
    match settings.alert_webhook_format:
        case "slack":
            return {"text": message}
        case "discord":
            return {"content": message}
        case "telegram":
            if not settings.alert_webhook_chat_id:
                raise ValueError("ALERT_WEBHOOK_CHAT_ID is required for the telegram format")
            return {"chat_id": settings.alert_webhook_chat_id, "text": message}


async def post_alert(settings: Settings, message: str) -> None:
    """Send `message` to the team chat; no-op without `ALERT_WEBHOOK_URL`."""
    url = settings.alert_webhook_url.get_secret_value()
    if not url:
        return
    payload = alert_payload(settings, message)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as http:
        (await http.post(url, json=payload)).raise_for_status()
