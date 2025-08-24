from datetime import datetime

from fastapi import Query
from pydantic import BaseModel, Field


class CreateWithdrawData(BaseModel):
    title: str = Query(...)
    min_withdrawable: int = Query(..., ge=1)
    max_withdrawable: int = Query(..., ge=1)
    uses: int = Query(..., ge=1)
    wait_time: int = Query(..., ge=1)
    is_unique: bool
    webhook_url: str = Query(None)
    webhook_headers: str = Query(None)
    webhook_body: str = Query(None)
    custom_url: str = Query(None)


class WithdrawLink(BaseModel):
    id: str
    wallet: str = Query(None)
    title: str = Query(None)
    min_withdrawable: int = Query(0)
    max_withdrawable: int = Query(0)
    uses: int = Query(0)
    wait_time: int = Query(0)
    is_unique: bool = Query(False)
    unique_hash: str = Query(0)
    k1: str = Query(None)
    open_time: int = Query(0)
    used: int = Query(0)
    usescsv: str = Query(None)
    number: int = Field(default=0, no_database=True)
    webhook_url: str = Query(None)
    webhook_headers: str = Query(None)
    webhook_body: str = Query(None)
    custom_url: str = Query(None)
    created_at: datetime

    @property
    def is_spent(self) -> bool:
        return self.used >= self.uses


class HashCheck(BaseModel):
    hash: bool
    lnurl: bool


class PaginatedWithdraws(BaseModel):
    data: list[WithdrawLink]
    total: int
