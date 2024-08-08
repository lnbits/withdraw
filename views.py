from http import HTTPStatus
from io import BytesIO

import pyqrcode
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from lnbits.core.models import User
from lnbits.decorators import check_user_exists
from lnbits.helpers import template_renderer

from .crud import chunks, get_withdraw_link

withdraw_ext_generic = APIRouter()


def withdraw_renderer():
    return template_renderer(["withdraw/templates"])


@withdraw_ext_generic.get("/", response_class=HTMLResponse)
async def index(request: Request, user: User = Depends(check_user_exists)):
    return withdraw_renderer().TemplateResponse(
        "withdraw/index.html", {"request": request, "user": user.dict()}
    )


@withdraw_ext_generic.get("/{link_id}", response_class=HTMLResponse)
async def display(request: Request, link_id):
    link = await get_withdraw_link(link_id)

    if not link:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Withdraw link does not exist."
        )
    return withdraw_renderer().TemplateResponse(
        "withdraw/display.html",
        {
            "request": request,
            "link": link.dict(),
            "lnurl": link.lnurl(req=request),
            "unique": True,
        },
    )


@withdraw_ext_generic.get("/img/{link_id}", response_class=StreamingResponse)
async def img(request: Request, link_id):
    link = await get_withdraw_link(link_id)
    if not link:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Withdraw link does not exist."
        )
    qr = pyqrcode.create(link.lnurl(request))
    stream = BytesIO()
    qr.svg(stream, scale=3)
    stream.seek(0)

    async def _generator(stream: BytesIO):
        yield stream.getvalue()

    return StreamingResponse(
        _generator(stream),
        headers={
            "Content-Type": "image/svg+xml",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@withdraw_ext_generic.get("/print/{link_id}", response_class=HTMLResponse)
async def print_qr(request: Request, link_id):
    link = await get_withdraw_link(link_id)
    if not link:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Withdraw link does not exist."
        )

    if link.uses == 0:
        return withdraw_renderer().TemplateResponse(
            "withdraw/print_qr.html",
            {"request": request, "link": link.dict(), "unique": False},
        )

    links = [link.lnurl(request, num=i) for i in range(len(link.usescsv.split(",")))]
    page_link = list(chunks(links, 2))
    linked = list(chunks(page_link, 5))

    if link.custom_url:
        return withdraw_renderer().TemplateResponse(
            "withdraw/print_qr_custom.html",
            {
                "request": request,
                "link": page_link,
                "unique": True,
                "custom_url": link.custom_url,
                "amt": link.max_withdrawable,
            },
        )

    return withdraw_renderer().TemplateResponse(
        "withdraw/print_qr.html", {"request": request, "link": linked, "unique": True}
    )


@withdraw_ext_generic.get("/csv/{link_id}", response_class=HTMLResponse)
async def csv(request: Request, link_id):
    link = await get_withdraw_link(link_id)
    if not link:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Withdraw link does not exist."
        )

    if not link.is_unique:
        return withdraw_renderer().TemplateResponse(
            "withdraw/csv.html",
            {"request": request, "link": link.dict(), "unique": False},
        )

    links = [link.lnurl(request, num=i) for i in range(len(link.usescsv.split(",")))]
    page_link = list(chunks(links, 2))
    linked = list(chunks(page_link, 5))

    return withdraw_renderer().TemplateResponse(
        "withdraw/csv.html", {"request": request, "link": linked, "unique": True}
    )
