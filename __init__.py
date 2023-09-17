from fastapi import APIRouter, Request, Response
from fastapi.routing import APIRoute

from fastapi.responses import JSONResponse

from lnbits.db import Database
from lnbits.helpers import template_renderer
from typing import Callable

db = Database("ext_withdraw")

withdraw_static_files = [
    {
        "path": "/withdraw/static",
        "name": "withdraw_static",
    }
]


class LNURLErrorResponseHandler(APIRoute):
    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            try:
                response = await original_route_handler(request)
            except HTTPException as exc:
                logger.debug(f"HTTPException: {exc}")
                response = JSONResponse(
                    status_code=exc.status_code,
                    content={"status": "ERROR", "reason": f"{exc.detail}"},
                )
            except Exception as exc:
                raise exc

            return response

        return custom_route_handler


withdraw_ext: APIRouter = APIRouter(prefix="/withdraw", tags=["withdraw"])
withdraw_ext.route_class = LNURLErrorResponseHandler


def withdraw_renderer():
    return template_renderer(["withdraw/templates"])


from .lnurl import *  # noqa: F401,F403
from .views import *  # noqa: F401,F403
from .views_api import *  # noqa: F401,F403
