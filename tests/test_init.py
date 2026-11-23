from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.responses import HTMLResponse
from lnbits import decorators
from lnbits.core.models import Wallet

from .. import views, views_api, views_lnurl, withdraw_ext
from ..models import PaginatedWithdraws, WithdrawLink


def test_router():
    router = APIRouter()
    router.include_router(withdraw_ext)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client(monkeypatch):
    app = FastAPI()
    app.include_router(withdraw_ext)
    monkeypatch.setattr(decorators, "db", MagicMock())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://lnbits.example"
    ) as http_client:
        yield http_client, app


@pytest.fixture
def link():
    return WithdrawLink(
        id="link",
        wallet="wallet",
        title="Voucher",
        min_withdrawable=1,
        max_withdrawable=10,
        uses=1,
        wait_time=1,
        is_unique=False,
        unique_hash="voucher",
        k1="challenge",
        open_time=0,
        used=0,
        usescsv="0",
        created_at=datetime(2026, 1, 1),
        enabled=True,
        expiry_seconds=0,
    )


@pytest.mark.anyio
async def test_management_reads_require_admin_key(client, link, monkeypatch):
    http_client, _ = client
    wallet = Wallet(
        id="wallet", user="owner", name="Wallet", adminkey="admin", inkey="invoice"
    )
    monkeypatch.setattr(
        decorators, "get_wallet_for_key", AsyncMock(return_value=wallet)
    )
    monkeypatch.setattr(decorators, "_check_user_access", AsyncMock())
    get_user = AsyncMock(return_value=SimpleNamespace(wallet_ids=["wallet", "second"]))
    monkeypatch.setattr(views_api, "get_user", get_user)
    get_links = AsyncMock(return_value=PaginatedWithdraws(data=[link], total=1))
    monkeypatch.setattr(views_api, "get_withdraw_links", get_links)
    monkeypatch.setattr(views_api, "get_withdraw_link", AsyncMock(return_value=link))

    base = "/withdraw/api/v1/links"
    for path in (base, f"{base}?all_wallets=true", f"{base}/{link.id}"):
        response = await http_client.get(path, headers={"X-Api-Key": "invoice"})
        assert response.status_code == 403
    get_user.assert_not_awaited()
    get_links.assert_not_awaited()

    headers = {"X-Api-Key": "admin"}
    listed = await http_client.get(f"{base}?all_wallets=true", headers=headers)
    assert listed.status_code == 200
    get_user.assert_awaited_once_with("owner")
    get_links.assert_awaited_once_with(["wallet", "second"], 0, 0)
    detail = await http_client.get(f"{base}/{link.id}", headers=headers)
    assert detail.status_code == 200
    lnurl_url = detail.json()["lnurl_url"]
    assert lnurl_url
    assert listed.json()["data"][0]["lnurl_url"] == lnurl_url


@pytest.mark.anyio
async def test_exports_require_owner_and_issued_voucher_stays_public(
    client, link, monkeypatch
):
    http_client, app = client
    monkeypatch.setattr(views, "get_withdraw_link", AsyncMock(return_value=link))
    renderer = SimpleNamespace(TemplateResponse=Mock(return_value=HTMLResponse("QR")))
    monkeypatch.setattr(views, "withdraw_renderer", lambda: renderer)
    paths = (f"/withdraw/print/{link.id}", f"/withdraw/csv/{link.id}")

    for path in paths:
        assert (await http_client.get(path)).status_code == 401

    user = SimpleNamespace(wallet_ids=[])
    app.dependency_overrides[decorators.check_user_exists] = lambda: user
    for wallet_ids, expected in ((["foreign"], 403), (["wallet"], 200)):
        user.wallet_ids = wallet_ids
        for path in paths:
            assert (await http_client.get(path)).status_code == expected

    app.dependency_overrides.clear()
    assert (await http_client.get(f"/withdraw/{link.id}")).status_code == 200
    monkeypatch.setattr(
        views_lnurl, "get_withdraw_link_by_hash", AsyncMock(return_value=link)
    )
    response = await http_client.get(f"/withdraw/api/v1/lnurl/{link.unique_hash}")
    assert response.status_code == 200
    assert response.json()["tag"] == "withdrawRequest"
