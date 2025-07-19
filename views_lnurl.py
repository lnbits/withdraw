import json
from datetime import datetime
from typing import Optional

import httpx
import shortuuid
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from lnbits.core.crud import update_payment
from lnbits.core.models import Payment
from lnbits.core.services import pay_invoice
from lnurl import (
    CallbackUrl,
    LnurlErrorResponse,
    LnurlSuccessResponse,
    LnurlWithdrawResponse,
    MilliSatoshi,
)
from loguru import logger
from pydantic import parse_obj_as

from .crud import (
    create_hash_check,
    delete_hash_check,
    get_withdraw_link_by_hash,
    increment_withdraw_link,
    remove_unique_withdraw_link,
)
from .models import WithdrawLink

withdraw_ext_lnurl = APIRouter(prefix="/api/v1/lnurl")


@withdraw_ext_lnurl.get(
    "/{unique_hash}",
    response_class=JSONResponse,
    name="withdraw.api_lnurl_response",
)
async def api_lnurl_response(
    request: Request, unique_hash: str
) -> LnurlWithdrawResponse | LnurlErrorResponse:
    link = await get_withdraw_link_by_hash(unique_hash)

    if not link:
        return LnurlErrorResponse(reason="Withdraw link does not exist.")

    if link.is_spent:
        return LnurlErrorResponse(reason="Withdraw is spent.")

    if link.is_unique:
        return LnurlErrorResponse(reason="This link requires an id_unique_hash.")

    url = str(
        request.url_for("withdraw.api_lnurl_callback", unique_hash=link.unique_hash)
    )

    callback_url = parse_obj_as(CallbackUrl, url)
    return LnurlWithdrawResponse(
        # tag="withdrawRequest",
        callback=callback_url,
        k1=link.k1,
        minWithdrawable=MilliSatoshi(link.min_withdrawable * 1000),
        maxWithdrawable=MilliSatoshi(link.max_withdrawable * 1000),
        defaultDescription=link.title,
        # TODO webhook are off spec in the response
        #     "webhook_url": link.webhook_url,
        #     "webhook_headers": link.webhook_headers,
        #     "webhook_body": link.webhook_body,
    )


@withdraw_ext_lnurl.get(
    "/cb/{unique_hash}",
    name="withdraw.api_lnurl_callback",
    summary="lnurl withdraw callback",
    description="""
        This endpoints allows you to put unique_hash, k1
        and a payment_request to get your payment_request paid.
    """,
    response_class=JSONResponse,
    response_description="JSON with status",
    responses={
        200: {"description": "status: OK"},
        400: {"description": "k1 is wrong or link open time or withdraw not working."},
        404: {"description": "withdraw link not found."},
        405: {"description": "withdraw link is spent."},
    },
)
async def api_lnurl_callback(
    unique_hash: str,
    k1: str,
    pr: str,
    id_unique_hash: Optional[str] = None,
) -> LnurlErrorResponse | LnurlSuccessResponse:

    link = await get_withdraw_link_by_hash(unique_hash)
    if not link:
        return LnurlErrorResponse(reason="withdraw link not found.")

    if link.is_spent:
        return LnurlErrorResponse(reason="withdraw is spent.")

    if link.k1 != k1:
        return LnurlErrorResponse(reason="k1 is wrong.")

    now = int(datetime.now().timestamp())

    if now < link.open_time:
        return LnurlErrorResponse(
            reason=f"wait link open_time {link.open_time - now} seconds."
        )

    if not id_unique_hash and link.is_unique:
        return LnurlErrorResponse(reason="id_unique_hash is required for this link.")

    if id_unique_hash:
        if check_unique_link(link, id_unique_hash):
            await remove_unique_withdraw_link(link, id_unique_hash)
        else:
            return LnurlErrorResponse(reason="id_unique_hash not found.")

    # Create a record with the id_unique_hash or unique_hash, if it already exists,
    # raise an exception thus preventing the same LNURL from being processed twice.
    try:
        await create_hash_check(id_unique_hash or unique_hash, k1)
    except Exception:
        return LnurlErrorResponse(reason="LNURL already being processed.")

    try:
        payment = await pay_invoice(
            wallet_id=link.wallet,
            payment_request=pr,
            max_sat=link.max_withdrawable,
            extra={"tag": "withdraw", "withdrawal_link_id": link.id},
        )
        await increment_withdraw_link(link)
        # If the payment succeeds, delete the record with the unique_hash.
        # TODO: we delete this now: "If it has unique_hash, do not delete to prevent
        # the same LNURL from being processed twice."
        await delete_hash_check(id_unique_hash or unique_hash)

        if link.webhook_url:
            await dispatch_webhook(link, payment, pr)
        return LnurlSuccessResponse()
    except Exception as exc:
        # If payment fails, delete the hash stored so another attempt can be made.
        await delete_hash_check(id_unique_hash or unique_hash)
        return LnurlErrorResponse(reason=f"withdraw not working. {exc!s}")


def check_unique_link(link: WithdrawLink, unique_hash: str) -> bool:
    return any(
        unique_hash == shortuuid.uuid(name=link.id + link.unique_hash + x.strip())
        for x in link.usescsv.split(",")
    )


async def dispatch_webhook(
    link: WithdrawLink, payment: Payment, payment_request: str
) -> None:
    async with httpx.AsyncClient() as client:
        try:
            r: httpx.Response = await client.post(
                link.webhook_url,
                json={
                    "payment_hash": payment.payment_hash,
                    "payment_request": payment_request,
                    "lnurlw": link.id,
                    "body": json.loads(link.webhook_body) if link.webhook_body else "",
                },
                headers=(
                    json.loads(link.webhook_headers) if link.webhook_headers else None
                ),
                timeout=40,
            )
            payment.extra["wh_success"] = r.is_success
            payment.extra["wh_message"] = r.reason_phrase
            payment.extra["wh_response"] = r.text
            await update_payment(payment)
        except Exception as exc:
            # webhook fails shouldn't cause the lnurlw to fail
            # since invoice is already paid
            logger.error(f"Caught exception when dispatching webhook url: {exc!s}")
            payment.extra["wh_success"] = False
            payment.extra["wh_message"] = str(exc)
            await update_payment(payment)


# FOR LNURLs WHICH ARE UNIQUE
@withdraw_ext_lnurl.get(
    "/{unique_hash}/{id_unique_hash}",
    response_class=JSONResponse,
    name="withdraw.api_lnurl_multi_response",
)
async def api_lnurl_multi_response(
    request: Request, unique_hash: str, id_unique_hash: str
) -> LnurlWithdrawResponse | LnurlErrorResponse:
    link = await get_withdraw_link_by_hash(unique_hash)

    if not link:
        return LnurlErrorResponse(reason="Withdraw link does not exist.")

    if link.is_spent:
        return LnurlErrorResponse(reason="Withdraw is spent.")

    if not check_unique_link(link, id_unique_hash):
        return LnurlErrorResponse(reason="id_unique_hash not found for this link.")

    url = request.url_for("withdraw.api_lnurl_callback", unique_hash=link.unique_hash)

    callback_url = parse_obj_as(CallbackUrl, f"{url!s}?id_unique_hash={id_unique_hash}")
    return LnurlWithdrawResponse(
        callback=callback_url,
        k1=link.k1,
        minWithdrawable=MilliSatoshi(link.min_withdrawable * 1000),
        maxWithdrawable=MilliSatoshi(link.max_withdrawable * 1000),
        defaultDescription=link.title,
    )
