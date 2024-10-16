import json
from datetime import datetime
from http import HTTPStatus
from typing import Callable, Optional
from urllib.parse import urlparse

import httpx
import shortuuid
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from lnbits.core.crud import update_payment
from lnbits.core.models import Payment
from lnbits.core.services import pay_invoice
from loguru import logger

from .crud import (
    create_hash_check,
    delete_hash_check,
    get_withdraw_link_by_hash,
    increment_withdraw_link,
    remove_unique_withdraw_link,
)
from .models import WithdrawLink


class LNURLErrorResponseHandler(APIRoute):
    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            try:
                response = await original_route_handler(request)
                return response
            except HTTPException as exc:
                logger.debug(f"HTTPException: {exc}")
                response = JSONResponse(
                    status_code=200,
                    content={"status": "ERROR", "reason": f"{exc.detail}"},
                )
                return response

        return custom_route_handler


withdraw_ext_lnurl = APIRouter(prefix="/api/v1/lnurl")
withdraw_ext_lnurl.route_class = LNURLErrorResponseHandler


@withdraw_ext_lnurl.get(
    "/{unique_hash}",
    response_class=JSONResponse,
    name="withdraw.api_lnurl_response",
)
async def api_lnurl_response(request: Request, unique_hash: str):
    link = await get_withdraw_link_by_hash(unique_hash)

    if not link:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Withdraw link does not exist."
        )

    if link.is_spent:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Withdraw is spent."
        )

    if link.is_unique:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="This link requires an id_unique_hash.",
        )

    url = str(
        request.url_for("withdraw.api_lnurl_callback", unique_hash=link.unique_hash)
    )

    # Check if url is .onion and change to http
    if urlparse(url).netloc.endswith(".onion"):
        # change url string scheme to http
        url = url.replace("https://", "http://")

    return {
        "tag": "withdrawRequest",
        "callback": url,
        "k1": link.k1,
        "minWithdrawable": link.min_withdrawable * 1000,
        "maxWithdrawable": link.max_withdrawable * 1000,
        "defaultDescription": link.title,
        "webhook_url": link.webhook_url,
        "webhook_headers": link.webhook_headers,
        "webhook_body": link.webhook_body,
    }


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
):

    link = await get_withdraw_link_by_hash(unique_hash)
    if not link:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="withdraw not found."
        )

    if link.is_spent:
        raise HTTPException(
            status_code=HTTPStatus.METHOD_NOT_ALLOWED, detail="withdraw is spent."
        )

    if link.k1 != k1:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="k1 is wrong.")

    now = int(datetime.now().timestamp())

    if now < link.open_time:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=f"wait link open_time {link.open_time - now} seconds.",
        )

    if not id_unique_hash and link.is_unique:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="id_unique_hash is required for this link.",
        )

    if id_unique_hash:
        if check_unique_link(link, id_unique_hash):
            await remove_unique_withdraw_link(link, id_unique_hash)
        else:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND, detail="withdraw not found."
            )

    # Create a record with the id_unique_hash or unique_hash, if it already exists,
    # raise an exception thus preventing the same LNURL from being processed twice.
    try:
        await create_hash_check(id_unique_hash or unique_hash, k1)
    except Exception as exc:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail="LNURL already being processed."
        ) from exc

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
        return {"status": "OK"}
    except Exception as exc:
        # If payment fails, delete the hash stored so another attempt can be made.
        await delete_hash_check(id_unique_hash or unique_hash)
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail=f"withdraw not working. {exc!s}"
        ) from exc


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
):
    link = await get_withdraw_link_by_hash(unique_hash)

    if not link:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="LNURL-withdraw not found."
        )

    if link.is_spent:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Withdraw is spent."
        )

    if not check_unique_link(link, id_unique_hash):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="LNURL-withdraw not found."
        )

    url = str(
        request.url_for("withdraw.api_lnurl_callback", unique_hash=link.unique_hash)
    )

    # Check if url is .onion and change to http
    if urlparse(url).netloc.endswith(".onion"):
        # change url string scheme to http
        url = url.replace("https://", "http://")

    return {
        "tag": "withdrawRequest",
        "callback": f"{url}?id_unique_hash={id_unique_hash}",
        "k1": link.k1,
        "minWithdrawable": link.min_withdrawable * 1000,
        "maxWithdrawable": link.max_withdrawable * 1000,
        "defaultDescription": link.title,
    }
