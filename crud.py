from lnbits.db import Database

from .models import CreateWithdrawData, PaginatedWithdraws, WithdrawLink, WithdrawSecret

db = Database("ext_withdraw")


async def create_withdraw_link(
    data: CreateWithdrawData, wallet_id: str
) -> WithdrawLink:
    withdraw_link = WithdrawLink(
        title=data.title,
        wallet=data.wallet or wallet_id,
        min_withdrawable=data.min_withdrawable,
        max_withdrawable=data.max_withdrawable,
        wait_time=data.wait_time,
        is_static=data.is_static,
        webhook_url=data.webhook_url,
        webhook_headers=data.webhook_headers,
        webhook_body=data.webhook_body,
        custom_url=data.custom_url,
    )
    secrets = []
    for _ in range(data.uses):
        secrets.append(
            WithdrawSecret(
                withdraw_id=withdraw_link.id,
                amount=withdraw_link.max_withdrawable,
            )
        )
    withdraw_link.secrets.total = data.uses
    withdraw_link.secrets.items = secrets
    await db.insert("withdraw.withdraw_link", withdraw_link)
    return withdraw_link


async def get_withdraw_link(link_id: str) -> WithdrawLink | None:
    return await db.fetchone(
        "SELECT * FROM withdraw.withdraw_link WHERE id = :id",
        {"id": link_id},
        WithdrawLink,
    )


async def get_withdraw_link_by_k1(k1: str) -> WithdrawLink | None:
    return await db.fetchone(
        "SELECT * FROM withdraw.withdraw_link WHERE secrets LIKE '%:k1%'",
        {"k1": k1},
        WithdrawLink,
    )


async def get_withdraw_links(
    wallet_ids: list[str], limit: int, offset: int
) -> PaginatedWithdraws:
    q = ",".join([f"'{w}'" for w in wallet_ids])

    query_str = f"""
        SELECT * FROM withdraw.withdraw_link WHERE wallet IN ({q})
        ORDER BY open_time DESC
        """

    if limit > 0:
        query_str += """ LIMIT :limit OFFSET :offset"""
        query_params = {"limit": limit, "offset": offset}
    else:
        query_params = {}

    links = await db.fetchall(
        query_str,
        query_params,
        WithdrawLink,
    )
    result = await db.execute(
        f"""
        SELECT COUNT(*) as total FROM withdraw.withdraw_link
        WHERE wallet IN ({q})
        """
    )
    result2 = result.mappings().first()

    return PaginatedWithdraws(data=links, total=int(result2.total))


async def update_withdraw_link(link: WithdrawLink) -> WithdrawLink:
    await db.update("withdraw.withdraw_link", link)
    return link


async def delete_withdraw_link(link_id: str) -> None:
    await db.execute(
        "DELETE FROM withdraw.withdraw_link WHERE id = :id", {"id": link_id}
    )
