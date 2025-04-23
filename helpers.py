from fastapi import Request
from lnurl import Lnurl
from lnurl import encode as lnurl_encode
from shortuuid import uuid

from .models import WithdrawLink


def create_lnurl(link: WithdrawLink, req: Request) -> Lnurl:
    if link.is_unique:
        usescssv = link.usescsv.split(",")
        tohash = link.id + link.unique_hash + usescssv[link.number]
        multihash = uuid(name=tohash)
        url = req.url_for(
            "withdraw.api_lnurl_multi_response",
            unique_hash=link.unique_hash,
            id_unique_hash=multihash,
        )
    else:
        url = req.url_for("withdraw.api_lnurl_response", unique_hash=link.unique_hash)

    try:
        return lnurl_encode(str(url))
    except Exception as e:
        raise ValueError(
            f"Error creating LNURL with url: `{url!s}`, "
            "check your webserver proxy configuration."
        ) from e
