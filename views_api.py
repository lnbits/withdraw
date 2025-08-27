from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException, Query
from lnbits.core.crud import get_user
from lnbits.core.models import SimpleStatus, WalletTypeInfo
from lnbits.decorators import require_admin_key

from .crud import (
    create_withdraw_link,
    delete_withdraw_link,
    get_withdraw_link,
    get_withdraw_links,
    update_withdraw_link,
)
from .models import CreateWithdrawData, PaginatedWithdraws, WithdrawLink

withdraw_ext_api = APIRouter(prefix="/api/v1")


@withdraw_ext_api.get("/links")
async def api_links(
    key_info: WalletTypeInfo = Depends(require_admin_key),
    all_wallets: bool = Query(False),
    offset: int = Query(0),
    limit: int = Query(0),
) -> PaginatedWithdraws:
    wallet_ids = [key_info.wallet.id]

    if all_wallets:
        user = await get_user(key_info.wallet.user)
        wallet_ids = user.wallet_ids if user else []

    return await get_withdraw_links(wallet_ids, limit, offset)


@withdraw_ext_api.get("/links/{link_id}")
async def api_link_retrieve(
    link_id: str, key_info: WalletTypeInfo = Depends(require_admin_key)
) -> WithdrawLink:
    link = await get_withdraw_link(link_id)

    if not link:
        raise HTTPException(
            detail="Withdraw link does not exist.", status_code=HTTPStatus.NOT_FOUND
        )

    if link.wallet != key_info.wallet.id:
        raise HTTPException(
            detail="Not your withdraw link.", status_code=HTTPStatus.FORBIDDEN
        )
    return link


@withdraw_ext_api.post("/links", status_code=HTTPStatus.CREATED)
async def api_link_create(
    data: CreateWithdrawData,
    key_info: WalletTypeInfo = Depends(require_admin_key),
) -> WithdrawLink:
    link = await create_withdraw_link(data, key_info.wallet.id)
    return link


@withdraw_ext_api.put("/links/{link_id}")
async def api_link_update(
    link_id: str,
    data: CreateWithdrawData,
    key_info: WalletTypeInfo = Depends(require_admin_key),
) -> WithdrawLink:
    link = await get_withdraw_link(link_id)
    if not link:
        raise HTTPException(
            detail="Withdraw link does not exist.", status_code=HTTPStatus.NOT_FOUND
        )
    if link.wallet != key_info.wallet.id:
        raise HTTPException(
            detail="Not your withdraw link.", status_code=HTTPStatus.FORBIDDEN
        )

    for k, v in data.dict().items():
        if k == "uses":
            continue
        setattr(link, k, v)

    return await update_withdraw_link(link)


@withdraw_ext_api.delete("/links/{link_id}")
async def api_link_delete(
    link_id: str, key_info: WalletTypeInfo = Depends(require_admin_key)
) -> SimpleStatus:
    link = await get_withdraw_link(link_id)

    if not link:
        raise HTTPException(
            detail="Withdraw link does not exist.", status_code=HTTPStatus.NOT_FOUND
        )

    if link.wallet != key_info.wallet.id:
        raise HTTPException(
            detail="Not your withdraw link.", status_code=HTTPStatus.FORBIDDEN
        )

    await delete_withdraw_link(link_id)
    return SimpleStatus(success=True, message="Withdraw link deleted.")
