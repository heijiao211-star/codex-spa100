from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from .errors import SourceUnavailableError

PUSHPLUS_URL = "https://www.pushplus.plus/send"


def send_pushplus(token: str, title: str, content: str, topic: str | None = None) -> dict[str, Any]:
    """Send a compact report with bounded retries and validated JSON response."""
    payload: dict[str, Any] = {"token": token, "title": title, "content": content, "template": "html"}
    if topic:
        payload["topic"] = topic
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    error: Exception | None = None
    for attempt in range(1, 4):
        try:
            request = urllib.request.Request(
                PUSHPLUS_URL,
                data=body,
                method="POST",
                headers={"Content-Type": "application/json;charset=utf-8", "User-Agent": "codex-spa100-public-fund-report/2.0"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                if not 200 <= response.getcode() < 300:
                    raise SourceUnavailableError(f"PushPlus HTTP {response.getcode()}")
                raw = response.read().decode("utf-8-sig", errors="strict")
            result = json.loads(raw)
            if result.get("code") != 200:
                raise SourceUnavailableError(f"PushPlus rejected request: {result.get('code')} {result.get('msg')}")
            return result
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            SourceUnavailableError,
        ) as exc:
            error = exc
            if attempt < 3:
                time.sleep(0.7 * attempt)
    raise SourceUnavailableError(f"PushPlus failed after 3 attempts: {type(error).__name__}: {error}")

