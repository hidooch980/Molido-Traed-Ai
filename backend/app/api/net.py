"""Who sent this request, as far as anything can tell (spec §52).

One function, and it exists because the rate limiter counts failures per
caller address - and an address the caller chooses is not a limit at all.

`X-Forwarded-For` is a header. Anyone can send one, with any contents, and a
naive reader takes the leftmost entry because that is documented as "the
original client". It is also the entry the client wrote. A limiter reading it
lets an attacker present a fresh address on every request, which is the same as
having no address rule, except that it also looks like one in the logs.

What is trustworthy is the right-hand end. Each proxy *appends* what it saw, so
with one proxy in front the last entry is what that proxy observed, and
everything to its left is whatever the caller sent. `trusted_proxy_hops` says
how many entries from the right were written by infrastructure this deployment
controls; the one before them is the earliest address that can be believed.

With zero hops the header is ignored completely and the socket address is used.
That is the safe default and the wrong answer behind a proxy - there, every
request appears to come from the proxy and the address ladder becomes one
bucket holding every caller in the world. Both failures are loud in different
ways, which is why the setting has no clever autodetection: it is a fact about
the deployment, and the deployment has to state it.
"""

from __future__ import annotations

from fastapi import Request

from app.core.config import get_settings

FORWARDED_FOR = "x-forwarded-for"


def client_address(request: Request, *, hops: int | None = None) -> str | None:
    """The caller's address, or None when nothing believable is available.

    None rather than a placeholder. `login_guard` skips its address rule when
    the address is unknown, and a stand-in like "unknown" would instead become
    a shared bucket that the first fifteen failed logins anywhere would fill.
    """
    trusted = get_settings().trusted_proxy_hops if hops is None else hops

    if trusted > 0:
        raw = request.headers.get(FORWARDED_FOR)
        if raw:
            chain = [part.strip() for part in raw.split(",") if part.strip()]
            # Counted from the right: `chain[-trusted]` is the address the
            # outermost proxy this deployment controls actually observed.
            # A caller who sends a header with fewer entries than there are
            # real hops gets their socket address used instead, which is the
            # conservative direction - it cannot be forged.
            if len(chain) >= trusted:
                return chain[-trusted][:64]

    client = request.client
    return client.host[:64] if client and client.host else None


def user_agent(request: Request) -> str | None:
    """What the caller says it is. Recorded, never believed."""
    value = request.headers.get("user-agent")
    return value[:256] if value else None
