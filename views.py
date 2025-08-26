import io
from datetime import datetime, timezone
from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from lnbits.core.models import User
from lnbits.decorators import check_user_exists
from lnbits.helpers import template_renderer
from lnurl import Lnurl
from pydantic import parse_obj_as

from .crud import get_withdraw_link

withdraw_ext_generic = APIRouter()


def withdraw_renderer():
    return template_renderer(["withdraw/templates"])


@withdraw_ext_generic.get("/")
async def index(
    request: Request, user: User = Depends(check_user_exists)
) -> HTMLResponse:
    return withdraw_renderer().TemplateResponse(
        "withdraw/index.html", {"request": request, "user": user.json()}
    )


@withdraw_ext_generic.get("/{link_id}")
async def display(request: Request, link_id: str) -> HTMLResponse:
    link = await get_withdraw_link(link_id)

    if not link:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Withdraw link does not exist."
        )

    if link.is_public is False:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail="Withdraw link is not public."
        )

    if link.open_time and link.open_time > datetime.now(timezone.utc).timestamp():
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Withdraw link is not yet active.",
        )

    return withdraw_renderer().TemplateResponse(
        "withdraw/display.html",
        {
            "request": request,
            "spent": link.secrets.is_spent,
            "secret": link.secrets.next_secret,
        },
    )


@withdraw_ext_generic.get("/print/{link_id}")
async def print_qr(
    request: Request, link_id: str, user: User = Depends(check_user_exists)
) -> HTMLResponse:
    link = await get_withdraw_link(link_id)
    if not link:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Withdraw link does not exist."
        )
    if link.wallet not in user.wallet_ids:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail="This is not your withdraw link."
        )
    links = []
    for secret in link.secrets.items:
        url = request.url_for("withdraw.lnurl", id_or_k1=secret.k1)
        lnurl = parse_obj_as(Lnurl, str(url))
        links.append(str(lnurl.bech32))

    return withdraw_renderer().TemplateResponse(
        "withdraw/print_qr.html", {"request": request, "links": links}
    )


@withdraw_ext_generic.get("/csv/{link_id}")
async def csv(
    req: Request, link_id: str, user: User = Depends(check_user_exists)
) -> StreamingResponse:
    link = await get_withdraw_link(link_id)
    if not link:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Withdraw link does not exist."
        )
    if link.wallet not in user.wallet_ids:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail="This is not your withdraw link."
        )

    buffer = io.StringIO()
    count = 0
    for secret in link.secrets.items:
        url = req.url_for("withdraw.lnurl", id_or_k1=secret.k1)
        lnurl = parse_obj_as(Lnurl, str(url))
        buffer.write(f"{lnurl.bech32!s}\n")
        count += 1

    # Move buffer cursor to the beginning
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=withdraw-links-{link_id}.csv"
        },
    )
