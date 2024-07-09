from fastapi import APIRouter

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

withdraw_ext: APIRouter = APIRouter(prefix="/withdraw", tags=["withdraw"])
withdraw_ext.include_router(withdraw_ext_generic)
withdraw_ext.include_router(withdraw_ext_api)
withdraw_ext.include_router(withdraw_ext_lnurl)

__all__ = ["withdraw_ext", "withdraw_static_files", "db"]
