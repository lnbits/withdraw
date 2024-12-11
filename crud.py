from datetime import datetime
from typing import Optional

import shortuuid
from lnbits.db import Database
from lnbits.helpers import urlsafe_short_hash

from .models import CreateWithdrawData, HashCheck, WithdrawLink

db = Database("ext_withdraw")


async def create_withdraw_link(
    data: CreateWithdrawData, wallet_id: str
) -> WithdrawLink:
    link_id = urlsafe_short_hash()[:22]
    available_links = ",".join([str(i) for i in range(data.uses)])
    withdraw_link = WithdrawLink(
        id=link_id,
        wallet=wallet_id,
        unique_hash=urlsafe_short_hash(),
        k1=urlsafe_short_hash(),
        created_at=datetime.now(),
        open_time=int(datetime.now().timestamp()) + data.wait_time,
        title=data.title,
        min_withdrawable=data.min_withdrawable,
        max_withdrawable=data.max_withdrawable,
        uses=data.uses,
        wait_time=data.wait_time,
        is_unique=data.is_unique,
        usescsv=available_links,
        webhook_url=data.webhook_url,
        webhook_headers=data.webhook_headers,
        webhook_body=data.webhook_body,
        custom_url=data.custom_url,
        number=0,
    )
    await db.insert("withdraw.withdraw_link", withdraw_link)
    return withdraw_link


async def get_withdraw_link(link_id: str, num=0) -> Optional[WithdrawLink]:
    link = await db.fetchone(
        "SELECT * FROM withdraw.withdraw_link WHERE id = :id",
        {"id": link_id},
        WithdrawLink,
    )
    if not link:
        return None

    link.number = num
    return link


async def get_withdraw_link_by_hash(unique_hash: str, num=0) -> Optional[WithdrawLink]:
    link = await db.fetchone(
        "SELECT * FROM withdraw.withdraw_link WHERE unique_hash = :hash",
        {"hash": unique_hash},
        WithdrawLink,
    )
    if not link:
        return None

    link.number = num
    return link


async def get_withdraw_links(
    wallet_ids: list[str], limit: int, offset: int
) -> tuple[list[WithdrawLink], int]:
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
    total = result.mappings().first()

    return links, total.total


async def remove_unique_withdraw_link(link: WithdrawLink, unique_hash: str) -> None:
    unique_links = [
        x.strip()
        for x in link.usescsv.split(",")
        if unique_hash != shortuuid.uuid(name=link.id + link.unique_hash + x.strip())
    ]
    link.usescsv = ",".join(unique_links)
    await update_withdraw_link(link)


async def increment_withdraw_link(link: WithdrawLink) -> None:
    link.used = link.used + 1
    link.open_time = int(datetime.now().timestamp()) + link.wait_time
    await update_withdraw_link(link)


async def update_withdraw_link(link: WithdrawLink) -> WithdrawLink:
    await db.update("withdraw.withdraw_link", link)
    return link


async def delete_withdraw_link(link_id: str) -> None:
    await db.execute(
        "DELETE FROM withdraw.withdraw_link WHERE id = :id", {"id": link_id}
    )


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


async def create_hash_check(the_hash: str, lnurl_id: str) -> HashCheck:
    await db.execute(
        """
        INSERT INTO withdraw.hash_check (id, lnurl_id)
        VALUES (:id, :lnurl_id)
        """,
        {"id": the_hash, "lnurl_id": lnurl_id},
    )
    hash_check = await get_hash_check(the_hash, lnurl_id)
    return hash_check


async def get_hash_check(the_hash: str, lnurl_id: str) -> HashCheck:

    hash_check = await db.fetchone(
        """
            SELECT id as hash, lnurl_id as lnurl
            FROM withdraw.hash_check WHERE id = :id
        """,
        {"id": the_hash},
        HashCheck,
    )
    hash_check_lnurl = await db.fetchone(
        """
            SELECT id as hash, lnurl_id as lnurl
            FROM withdraw.hash_check WHERE lnurl_id = :id
        """,
        {"id": lnurl_id},
        HashCheck,
    )
    if not hash_check_lnurl:
        await create_hash_check(the_hash, lnurl_id)
        return HashCheck(lnurl=True, hash=False)
    else:
        if not hash_check:
            await create_hash_check(the_hash, lnurl_id)
            return HashCheck(lnurl=True, hash=False)
        else:
            return HashCheck(lnurl=True, hash=True)


async def delete_hash_check(the_hash: str) -> None:
    await db.execute(
        "DELETE FROM withdraw.hash_check WHERE id = :hash", {"hash": the_hash}
    )
