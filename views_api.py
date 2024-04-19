import json
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from lnbits.core.crud import get_user
from lnbits.decorators import WalletTypeInfo, get_key_type, require_admin_key
from lnurl.exceptions import InvalidUrl as LnurlInvalidUrl

from .crud import (
    create_withdraw_link,
    delete_withdraw_link,
    get_hash_check,
    get_withdraw_link,
    get_withdraw_links,
    update_withdraw_link,
)
from .models import CreateWithdrawData

withdraw_ext_api = APIRouter(prefix="/api/v1")


@withdraw_ext_api.get("/links", status_code=HTTPStatus.OK)
async def api_links(
    req: Request,
    wallet: WalletTypeInfo = Depends(get_key_type),
    all_wallets: bool = Query(False),
):
    wallet_ids = [wallet.wallet.id]

    if all_wallets:
        user = await get_user(wallet.wallet.user)
        wallet_ids = user.wallet_ids if user else []

    try:
        return [
            {**link.dict(), **{"lnurl": link.lnurl(req)}}
            for link in await get_withdraw_links(wallet_ids)
        ]

    except LnurlInvalidUrl as exc:
        raise HTTPException(
            status_code=HTTPStatus.UPGRADE_REQUIRED,
            detail="""
                LNURLs need to be delivered over a publically
                accessible `https` domain or Tor.
            """,
        ) from exc


@withdraw_ext_api.get("/links/{link_id}", status_code=HTTPStatus.OK)
async def api_link_retrieve(
    link_id: str, request: Request, wallet: WalletTypeInfo = Depends(get_key_type)
):
    link = await get_withdraw_link(link_id, 0)

    if not link:
        raise HTTPException(
            detail="Withdraw link does not exist.", status_code=HTTPStatus.NOT_FOUND
        )

    if link.wallet != wallet.wallet.id:
        raise HTTPException(
            detail="Not your withdraw link.", status_code=HTTPStatus.FORBIDDEN
        )
    return {**link.dict(), **{"lnurl": link.lnurl(request)}}


@withdraw_ext_api.post("/links", status_code=HTTPStatus.CREATED)
@withdraw_ext_api.put("/links/{link_id}", status_code=HTTPStatus.OK)
async def api_link_create_or_update(
    req: Request,
    data: CreateWithdrawData,
    link_id: Optional[str] = None,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    if data.uses > 250:
        raise HTTPException(detail="250 uses max.", status_code=HTTPStatus.BAD_REQUEST)

    if data.min_withdrawable < 1:
        raise HTTPException(
            detail="Min must be more than 1.", status_code=HTTPStatus.BAD_REQUEST
        )

    if data.max_withdrawable < data.min_withdrawable:
        raise HTTPException(
            detail="`max_withdrawable` needs to be at least `min_withdrawable`.",
            status_code=HTTPStatus.BAD_REQUEST,
        )

    if data.webhook_body:
        try:
            json.loads(data.webhook_body)
        except Exception as exc:
            raise HTTPException(
                detail="`webhook_body` can not parse JSON.",
                status_code=HTTPStatus.BAD_REQUEST,
            ) from exc

    if data.webhook_headers:
        try:
            json.loads(data.webhook_headers)
        except Exception as exc:
            raise HTTPException(
                detail="`webhook_headers` can not parse JSON.",
                status_code=HTTPStatus.BAD_REQUEST,
            ) from exc

    if link_id:
        link = await get_withdraw_link(link_id, 0)
        if not link:
            raise HTTPException(
                detail="Withdraw link does not exist.", status_code=HTTPStatus.NOT_FOUND
            )
        if link.wallet != wallet.wallet.id:
            raise HTTPException(
                detail="Not your withdraw link.", status_code=HTTPStatus.FORBIDDEN
            )

        data_dict = data.dict()
        if link.uses > data.uses:
            if data.uses - link.used <= 0:
                raise HTTPException(
                    detail="Cannot reduce uses below current used.",
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            numbers = link.usescsv.split(",")
            usescsv = ",".join(numbers[: data.uses - link.used])
            data_dict["usescsv"] = usescsv

        if link.uses < data.uses:
            numbers = link.usescsv.split(",")
            
            if numbers[-1] == "":
                current_number = int(link.uses)
                numbers[-1] = str(link.uses)
            else:
                current_number = int(numbers[-1])
                
            while len(numbers) < (data.uses - link.used):
                current_number += 1
                numbers.append(str(current_number))
            usescsv = ",".join(numbers)
            data_dict["usescsv"] = usescsv

        link = await update_withdraw_link(link_id, **data_dict)
    else:
        link = await create_withdraw_link(wallet_id=wallet.wallet.id, data=data)
    assert link
    return {**link.dict(), **{"lnurl": link.lnurl(req)}}


@withdraw_ext_api.delete("/links/{link_id}", status_code=HTTPStatus.OK)
async def api_link_delete(link_id, wallet: WalletTypeInfo = Depends(require_admin_key)):
    link = await get_withdraw_link(link_id)

    if not link:
        raise HTTPException(
            detail="Withdraw link does not exist.", status_code=HTTPStatus.NOT_FOUND
        )

    if link.wallet != wallet.wallet.id:
        raise HTTPException(
            detail="Not your withdraw link.", status_code=HTTPStatus.FORBIDDEN
        )

    await delete_withdraw_link(link_id)
    return {"success": True}


@withdraw_ext_api.get(
    "/links/{the_hash}/{lnurl_id}",
    status_code=HTTPStatus.OK,
    dependencies=[Depends(get_key_type)],
)
async def api_hash_retrieve(the_hash, lnurl_id):
    hash_check = await get_hash_check(the_hash, lnurl_id)
    return hash_check
