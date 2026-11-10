import asyncio
import json
import socket
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import httpx
import pytest
from lnbits.core.models import Payment
from lnbits.settings import settings
from lnbits.utils import outbound
from lnbits.utils.safe_http import SafeHttpClient

from .. import views_lnurl as views
from ..models import WithdrawLink


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def callback_policy(monkeypatch):
    monkeypatch.setattr(settings, "lnbits_callback_url_rules", [])
    monkeypatch.setattr(settings, "lnbits_callback_allow_private_ips", False)
    monkeypatch.setattr(settings, "lnbits_baseurl", "http://localhost:5000")
    monkeypatch.setattr(settings, "lnbits_outbound_host_ips", [])
    monkeypatch.setattr(outbound, "_is_assigned", lambda address: address.is_loopback)


@pytest.fixture
def webhook_sender(monkeypatch):
    requests = []
    response = httpx.Response(200, text="server-secret")

    def factory(**kwargs):
        client = SafeHttpClient(**kwargs)

        def handler(request):
            requests.append(request)
            return response

        client.client._transport = httpx.MockTransport(handler)
        return client

    monkeypatch.setattr(views, "SafeHttpClient", factory)
    update = AsyncMock()
    monkeypatch.setattr(views, "update_payment", update)

    def resolve(*addresses):
        monkeypatch.setattr(
            asyncio.get_running_loop(),
            "getaddrinfo",
            AsyncMock(
                return_value=[
                    (
                        socket.AF_INET6 if ":" in address else socket.AF_INET,
                        socket.SOCK_STREAM,
                        6,
                        "",
                        (address, 8500),
                    )
                    for address in addresses
                ]
            ),
        )

    async def send(url):
        payment = SimpleNamespace(payment_hash="hash", extra={})
        link = SimpleNamespace(
            id="link", webhook_url=url, webhook_body="", webhook_headers=""
        )
        await views.dispatch_webhook(
            cast(WithdrawLink, link), cast(Payment, payment), "invoice"
        )
        update.assert_awaited_once_with(payment)
        assert payment.extra["wh_response"] == ""
        return payment.extra["wh_success"]

    return SimpleNamespace(
        send=send, resolve=resolve, requests=requests, response=response
    )


@pytest.mark.anyio
@pytest.mark.parametrize("allow_private", [False, True])
@pytest.mark.parametrize("address", ["127.0.0.1", "::1"])
async def test_explicit_origin_allows_local_webhook(
    webhook_sender, monkeypatch, allow_private, address
):
    monkeypatch.setattr(settings, "lnbits_callback_allow_private_ips", allow_private)
    monkeypatch.setattr(
        settings, "lnbits_callback_url_rules", ["http://localhost:8500"]
    )
    webhook_sender.resolve(address)

    assert await webhook_sender.send("http://localhost:8500/hook?token=secret")
    request = webhook_sender.requests[0]
    assert request.url.host == address
    assert request.url.port == 8500
    assert request.url.path == "/hook"
    assert request.headers["host"] == "localhost:8500"


@pytest.mark.anyio
@pytest.mark.parametrize("allow_private", [False, True])
async def test_private_ip_setting_controls_remote_lan_webhook(
    webhook_sender, monkeypatch, allow_private
):
    monkeypatch.setattr(settings, "lnbits_callback_allow_private_ips", allow_private)
    webhook_sender.resolve("10.0.0.10")

    assert (
        await webhook_sender.send("http://receiver.example:8500/hook") is allow_private
    )
    assert bool(webhook_sender.requests) is allow_private


@pytest.mark.anyio
@pytest.mark.parametrize(
    "rules",
    [[], [".*"], [r"http://localhost:\d+"], ["http://localhost:8500/hook"]],
)
async def test_only_literal_origin_grants_loopback_exception(
    webhook_sender, monkeypatch, rules
):
    monkeypatch.setattr(settings, "lnbits_callback_url_rules", rules)
    monkeypatch.setattr(settings, "lnbits_callback_allow_private_ips", True)
    webhook_sender.resolve("127.0.0.1")

    assert not await webhook_sender.send("http://localhost:8500/hook")
    assert not webhook_sender.requests


@pytest.mark.anyio
@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8501/hook",
        "https://localhost:8500/hook",
        "http://127.0.0.1:8500/hook",
        "http://user:password@localhost:8500/hook",
    ],
)
async def test_private_exception_is_scoped_to_origin(webhook_sender, monkeypatch, url):
    monkeypatch.setattr(
        settings, "lnbits_callback_url_rules", ["http://localhost:8500", ".*"]
    )
    monkeypatch.setattr(settings, "lnbits_callback_allow_private_ips", True)
    webhook_sender.resolve("127.0.0.1")

    assert not await webhook_sender.send(url)
    assert not webhook_sender.requests


@pytest.mark.anyio
async def test_explicit_origin_cannot_target_lnbits(webhook_sender, monkeypatch):
    monkeypatch.setattr(
        settings, "lnbits_callback_url_rules", ["http://localhost:5000"]
    )
    webhook_sender.resolve("127.0.0.1")

    assert not await webhook_sender.send("http://localhost:5000/admin")
    assert not webhook_sender.requests


@pytest.mark.anyio
@pytest.mark.parametrize(
    "addresses",
    [
        ["169.254.169.254"],
        ["fd00:ec2::254"],
        ["224.0.0.1"],
        ["93.184.216.34"],
        ["127.0.0.1", "93.184.216.34"],
    ],
)
async def test_explicit_origin_keeps_address_restrictions(
    webhook_sender, monkeypatch, addresses
):
    monkeypatch.setattr(
        settings, "lnbits_callback_url_rules", ["http://receiver.example:8500"]
    )
    monkeypatch.setattr(settings, "lnbits_outbound_host_ips", ["93.184.216.34"])
    webhook_sender.resolve(*addresses)

    assert not await webhook_sender.send("http://receiver.example:8500/hook")
    assert not webhook_sender.requests


@pytest.mark.anyio
async def test_explicit_origin_does_not_follow_redirects(webhook_sender, monkeypatch):
    monkeypatch.setattr(
        settings, "lnbits_callback_url_rules", ["http://localhost:8500"]
    )
    webhook_sender.resolve("127.0.0.1")
    webhook_sender.response.status_code = 302
    webhook_sender.response.headers["location"] = "http://localhost:5000/admin"

    assert not await webhook_sender.send("http://localhost:8500/hook")
    assert len(webhook_sender.requests) == 1
    assert webhook_sender.requests[0].url.port == 8500


@pytest.mark.anyio
@pytest.mark.parametrize("url", ["http://localhost:bad/hook", "file:///etc/passwd"])
async def test_invalid_url_does_not_fail_paid_withdrawal(webhook_sender, url):
    assert not await webhook_sender.send(url)
    assert not webhook_sender.requests


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
    await views.dispatch_webhook(
        cast(WithdrawLink, link), cast(Payment, payment), "invoice"
    )
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
    await views.dispatch_webhook(
        cast(WithdrawLink, link), cast(Payment, payment), "invoice"
    )
    assert payment.extra == {
        "wh_success": False,
        "wh_message": "Webhook request failed.",
        "wh_response": "",
    }
    update.assert_awaited_once_with(payment)
