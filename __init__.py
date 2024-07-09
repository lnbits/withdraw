from typing import Callable

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from loguru import logger

from .crud import db
from .views import withdraw_ext_generic
from .views_api import withdraw_ext_api
from .views_lnurl import withdraw_ext_lnurl

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
withdraw_ext.include_router(withdraw_ext_generic)
withdraw_ext.include_router(withdraw_ext_api)
withdraw_ext.include_router(withdraw_ext_lnurl)


__all__ = ["withdraw_ext", "withdraw_static_files", "db"]
