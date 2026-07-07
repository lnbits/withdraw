from datetime import datetime

from ..models import CreateWithdrawData, WithdrawLink


def test_update_omitted_expiry_seconds_preserves_existing_expiry():
    link = WithdrawLink(
        id="link_id",
        wallet="wallet_id",
        created_at=datetime.now(),
        expiry_seconds=86400,
    )
    data = CreateWithdrawData(
        title="updated",
        min_withdrawable=1,
        max_withdrawable=1,
        uses=1,
        wait_time=1,
        is_unique=False,
    )

    for key, value in data.dict().items():
        if value is not None:
            setattr(link, key, value)

    assert link.expiry_seconds == 86400
