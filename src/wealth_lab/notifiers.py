"""Notification adapters for later automation."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class FeishuWebhookNotifier:
    """Minimal Feishu bot webhook notifier."""

    webhook_url: str
    timeout_seconds: int = 10

    def send_text(self, text: str) -> None:
        """Send a text message to a Feishu bot webhook."""

        payload = json.dumps(
            {"msg_type": "text", "content": {"text": text}},
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            self.webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            if response.status >= 400:
                raise RuntimeError(f"Feishu webhook failed: HTTP {response.status}")

