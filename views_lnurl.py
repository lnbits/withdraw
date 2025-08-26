import json
from datetime import datetime

import httpx
from fastapi import APIRouter, Request
from lnbits.core.crud import update_payment
from lnbits.core.models import Payment
from lnbits.core.services import pay_invoice
from lnbits.exceptions import PaymentError
from lnurl import (
    CallbackUrl,
    InvalidLnurl,
    LnurlErrorResponse,
    LnurlSuccessResponse,
    LnurlWithdrawResponse,
    MilliSatoshi,
)
from loguru import logger
from pydantic import parse_obj_as

from .crud import get_withdraw_link, get_withdraw_link_by_k1, update_withdraw_link
from .models import WithdrawLink

withdraw_ext_lnurl = APIRouter(prefix="/api/v1/lnurl")


# note important that this endpoint is defined before the dynamic /{id_or_k1} endpoint
@withdraw_ext_lnurl.get("/cb", name="withdraw.lnurl_callback")
async def api_lnurl_callback(
    k1: str, pr: str
) -> LnurlErrorResponse | LnurlSuccessResponse:

    link = await get_withdraw_link_by_k1(k1)
    if not link:
        return LnurlErrorResponse(reason="Invalid k1.")

    secret = link.secrets.get_secret(k1)
    if not secret:
        return LnurlErrorResponse(reason="Invalid k1.")

    if secret.used:
        return LnurlErrorResponse(reason="Withdraw is spent.")

    # IMPORTANT: update the link in the db before paying the invoice
    # so that concurrent requests can't use the same secret
    link.open_time = int(datetime.now().timestamp()) + link.wait_time
    link.secrets.use_secret(k1)
    await update_withdraw_link(link)

    try:
        payment = await pay_invoice(
            wallet_id=link.wallet,
            payment_request=pr,
            max_sat=link.max_withdrawable,
            extra={"tag": "withdraw", "withdraw_id": link.id},
        )
    except PaymentError as exc:
        return LnurlErrorResponse(reason=f"Payment error: {exc.message}")

    if link.webhook_url:
        await dispatch_webhook(link, payment, pr)

    return LnurlSuccessResponse()


@withdraw_ext_lnurl.get("/{id_or_k1}", name="withdraw.lnurl")
async def api_lnurl_response(
    request: Request, id_or_k1: str
) -> LnurlWithdrawResponse | LnurlErrorResponse:
    link = await get_withdraw_link(id_or_k1)

    # static links are identified by their id
    if link:
        if not link.is_static:
            return LnurlErrorResponse(
                reason="Withdraw link is not static. Only use 'id' for static links."
            )
        secret = link.secrets.next_secret
        if not secret:
            return LnurlErrorResponse(reason="Withdraw is spent.")

    # non-static links are identified by their k1
    else:
        link = await get_withdraw_link_by_k1(id_or_k1)
        if not link:
            return LnurlErrorResponse(reason="Withdraw link does not exist.")
        secret = link.secrets.get_secret(id_or_k1)
        if not secret:
            return LnurlErrorResponse(reason="Invalid k1.")
        if secret.used:
            return LnurlErrorResponse(reason="Withdraw is spent.")

    now = int(datetime.now().timestamp())
    if now < link.open_time:
        return LnurlErrorResponse(
            reason=f"wait link open_time {link.open_time - now} seconds."
        )

    url = request.url_for("withdraw.lnurl_callback")
    try:
        callback_url = parse_obj_as(CallbackUrl, str(url))
    except InvalidLnurl:
        return LnurlErrorResponse(reason=f"Invalid callback URL. {url!s}")

    return LnurlWithdrawResponse(
        callback=callback_url,
        k1=secret.k1,
        minWithdrawable=MilliSatoshi(link.min_withdrawable * 1000),
        maxWithdrawable=MilliSatoshi(link.max_withdrawable * 1000),
        defaultDescription=link.title,
    )


async def dispatch_webhook(
    link: WithdrawLink, payment: Payment, payment_request: str
) -> None:
    if not link.webhook_url:
        return
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
