import json
from datetime import datetime, timezone

from fastapi import Query
from lnbits.helpers import urlsafe_short_hash
from pydantic import BaseModel, Field, validator


class CreateWithdrawData(BaseModel):
    title: str = Query(...)
    min_withdrawable: int = Query(..., ge=1)
    max_withdrawable: int = Query(..., ge=1)
    uses: int = Query(..., ge=1, le=250)
    wait_time: int = Query(..., ge=1)
    is_static: bool = Query(True)
    wallet: str | None = Query(None)
    webhook_url: str | None = Query(None)
    webhook_headers: str | None = Query(None)
    webhook_body: str | None = Query(None)
    custom_url: str | None = Query(None)

    @validator("max_withdrawable")
    def check_max_withdrawable(self, v, values):
        if "min_withdrawable" in values and v < values["min_withdrawable"]:
            raise ValueError("max_withdrawable must be at least min_withdrawable")
        return v

    @validator("webhook_body")
    def check_webhook_body(self, v):
        if v:
            try:
                json.loads(v)
            except Exception as exc:
                raise ValueError("webhook_body must be valid JSON") from exc
        return v

    @validator("webhook_headers")
    def check_headers_json(self, v):
        if v:
            try:
                json.loads(v)
            except Exception as exc:
                raise ValueError("webhook_headers must be valid JSON") from exc
        return v


class WithdrawSecret(BaseModel):
    k1: str = Field(default_factory=urlsafe_short_hash)
    withdraw_id: str
    amount: int | None = None
    used: bool = False
    used_at: int | None = None


class WithdrawSecrets(BaseModel):
    total: int = 0
    used: int = 0
    items: list[WithdrawSecret] = []

    @property
    def is_spent(self) -> bool:
        return self.used >= self.total

    @property
    def next_secret(self) -> WithdrawSecret | None:
        return next((item for item in self.items if not item.used), None)

    def get_secret(self, k1: str) -> WithdrawSecret | None:
        return next((item for item in self.items if item.k1 == k1), None)

    def use_secret(self, k1: str) -> WithdrawSecret | None:
        for item in self.items:
            if item.k1 == k1 and not item.used:
                item.used = True
                item.used_at = int(datetime.now().timestamp())
                self.used += 1
                return item
        return None


class WithdrawLink(BaseModel):
    id: str = Field(default_factory=lambda: urlsafe_short_hash()[:22])
    wallet: str
    title: str
    min_withdrawable: int
    max_withdrawable: int
    wait_time: int
    is_static: bool
    webhook_url: str | None = None
    webhook_headers: str | None = None
    webhook_body: str | None = None
    custom_url: str | None = None
    open_time: int = Field(default_factory=lambda: int(datetime.now().timestamp()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    secrets: WithdrawSecrets = WithdrawSecrets()


class PaginatedWithdraws(BaseModel):
    data: list[WithdrawLink]
    total: int
