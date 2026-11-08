import asyncio
import json
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from lnbits.settings import settings
from lnbits.utils.safe_http import SafeHttpClient

from .. import views_lnurl as views


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_webhook_payload_preserved_response_not_stored(monkeypatch):
    monkeypatch.setattr(settings, "lnbits_callback_url_rules", [])
    monkeypatch.setattr(
        asyncio.get_running_loop(),
        "getaddrinfo",
        AsyncMock(
            return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
            ]
        ),
    )
    seen = []

    def factory(**kwargs):
        client = SafeHttpClient(**kwargs)

        def handler(request):
            seen.append(request)
            return httpx.Response(200, text="server-secret")

        client.client._transport = httpx.MockTransport(handler)
        return client

    monkeypatch.setattr(views, "SafeHttpClient", factory)
    update = AsyncMock()
    monkeypatch.setattr(views, "update_payment", update)
    payment = SimpleNamespace(payment_hash="hash", extra={})
    link = SimpleNamespace(
        id="link",
        webhook_url="https://public.example/hook",
        webhook_body='{"custom":21}',
        webhook_headers='{"X-API-KEY":"key"}',
    )
    await views.dispatch_webhook(link, payment, "invoice")
    assert payment.extra == {
        "wh_success": True,
        "wh_message": "Webhook delivered.",
        "wh_response": "",
    }
    assert json.loads(seen[0].content) == {
        "payment_hash": "hash",
        "payment_request": "invoice",
        "lnurlw": "link",
        "body": {"custom": 21},
    }
    assert seen[0].headers["X-API-KEY"] == "key"
    update.assert_awaited_once_with(payment)


@pytest.mark.anyio
async def test_failed_webhook_does_not_fail_already_paid_withdrawal(monkeypatch):
    monkeypatch.setattr(settings, "lnbits_callback_url_rules", [])
    update = AsyncMock()
    monkeypatch.setattr(views, "update_payment", update)
    payment = SimpleNamespace(payment_hash="hash", extra={"wh_response": "old-secret"})
    link = SimpleNamespace(
        id="link",
        webhook_url="http://127.0.0.1/?token=secret",
        webhook_body="",
        webhook_headers="",
    )
    await views.dispatch_webhook(link, payment, "invoice")
    assert payment.extra == {
        "wh_success": False,
        "wh_message": "Webhook request failed.",
        "wh_response": "",
    }
    update.assert_awaited_once_with(payment)
