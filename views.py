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


@withdraw_ext_generic.get("/", response_class=HTMLResponse)
async def index(request: Request, user: User = Depends(check_user_exists)):
    return withdraw_renderer().TemplateResponse(
        "withdraw/index.html", {"request": request, "user": user.json()}
    )


@withdraw_ext_generic.get("/{link_id}", response_class=HTMLResponse)
async def display(request: Request, link_id):
    link = await get_withdraw_link(link_id)

    if not link:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Withdraw link does not exist."
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
            "unique_hash": link.secrets.next_secret,
        },
    )


@withdraw_ext_generic.get("/print/{link_id}", response_class=HTMLResponse)
async def print_qr(request: Request, link_id):
    link = await get_withdraw_link(link_id)
    if not link:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Withdraw link does not exist."
        )

    # if link.uses == 0:

    #     return withdraw_renderer().TemplateResponse(
    #         "withdraw/print_qr.html",
    #         {"request": request, "link": link.json(), "unique": False},
    #     )
    # links = []
    # count = 0

    # for _ in link.usescsv.split(","):
    #     linkk = await get_withdraw_link(link_id, count)
    #     if not linkk:
    #         raise HTTPException(
    #             HTTPStatus.NOT_FOUND, detail="Withdraw link does not exist."
    #         )
    #     try:
    #         lnurl = create_lnurl(linkk, request)
    #     except ValueError as exc:
    #         raise HTTPException(
    #             status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
    #             detail=str(exc),
    #         ) from exc
    #     links.append(str(lnurl.bech32))
    #     count = count + 1
    # page_link = list(chunks(links, 2))
    # linked = list(chunks(page_link, 5))

    return withdraw_renderer().TemplateResponse(
        "withdraw/print_qr.html", {"request": request, "link": [], "unique": True}
    )


@withdraw_ext_generic.get("/csv/{link_id}", response_class=HTMLResponse)
async def csv(req: Request, link_id):
    link = await get_withdraw_link(link_id)
    if not link:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Withdraw link does not exist."
        )

    buffer = io.StringIO()
    count = 0
    for _ in link.secrets.items:
        url = req.url_for("withdraw.lnurl_callback", id_or_secret=link_id)
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
