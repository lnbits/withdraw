from datetime import datetime, timedelta

from fastapi import Query
from pydantic import BaseModel, Field


class CreateWithdrawData(BaseModel):
    title: str = Query(...)
    min_withdrawable: float = Query(..., ge=0.01)
    max_withdrawable: float = Query(..., ge=0.01)
    uses: int = Query(..., ge=1)
    wait_time: int = Query(..., ge=1)
    is_unique: bool
    webhook_url: str = Query(None)
    webhook_headers: str = Query(None)
    webhook_body: str = Query(None)
    custom_url: str = Query(None)
    enabled: bool = Query(True)
    currency: str = Query(None)
    validity_seconds: int = Query(0, ge=0)


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
    enabled: bool = Query(True)
    currency: str = Query(None)
    validity_seconds: int = Query(0)
    lnurl: str | None = Field(
        default=None,
        no_database=True,
        deprecated=True,
        description=(
            "Deprecated: Instead of using this bech32 encoded string, dynamically "
            "generate your own static link (lud17/bech32) on the client side. "
            "Example: lnurlw://${window.location.hostname}/lnurlw/${id}"
        ),
    )
    lnurl_url: str | None = Field(
        default=None,
        no_database=True,
        description="The raw LNURL callback URL (use for QR code generation)",
    )

    @property
    def is_spent(self) -> bool:
        return self.used >= self.uses

    @property
    def expires_at(self) -> datetime | None:
        if self.validity_seconds <= 0:
            return None
        return self.created_at + timedelta(seconds=self.validity_seconds)

    @property
    def is_expired(self) -> bool:
        expires_at = self.expires_at
        return bool(expires_at and datetime.now(expires_at.tzinfo) > expires_at)


class HashCheck(BaseModel):
    hash: bool
    lnurl: bool


class PaginatedWithdraws(BaseModel):
    data: list[WithdrawLink]
    total: int
