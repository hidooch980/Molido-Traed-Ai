"""TradingView: a webhook that records alerts, and the page's view of them.

The webhook is public because TradingView holds no session or API key; it
proves itself with a secret in the body instead. A stored alert changes no
order, no risk and no brain - it is kept so it can be measured later.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.api.guard import public_mutation
from app.api.net import client_address
from app.core.enums import Permission
from app.db.session import get_db
from app.integrations import tradingview
from app.models.tradingview import TradingViewAlert, TradingViewConfig

router = APIRouter(prefix="/tradingview", tags=["tradingview"])

READ = Depends(require(Permission.READ))
SETTINGS_WRITE = Depends(require(Permission.SETTINGS_WRITE))

WEBHOOK_PATH = "/api/v1/tradingview/webhook"


def _config(session: Session) -> TradingViewConfig | None:
    return session.scalars(select(TradingViewConfig).limit(1)).first()


@router.post("/webhook", status_code=202)
@public_mutation(
    "TradingView holds no session or key; the request proves itself with the "
    "secret in its body, and a stored alert can change nothing"
)
async def receive(
    request: Request,
    _: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    if not tradingview.LIMIT.allow(client_address(request)):
        raise HTTPException(status_code=429, detail="too many alerts; slow down")
    raw = await request.body()
    if len(raw) > tradingview.MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="alert body is too large")
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=400,
            detail='the alert message must be JSON, e.g. {"secret": "...", "symbol": "{{ticker}}"}',
        )
    config = _config(session)
    if config is None or not config.enabled or not tradingview.secret_matches(
        body.get("secret"), config.secret_hash
    ):
        raise HTTPException(status_code=401, detail="the secret is missing or wrong")

    fields = tradingview.parse(body)
    alert = TradingViewAlert(**fields)
    session.add(alert)
    session.commit()
    return {"stored": True, "traded": False, "id": str(alert.id)}


@router.get("")
def read_state(
    _: Principal = READ,
    session: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    config = _config(session)
    total = session.scalar(select(func.count(TradingViewAlert.id))) or 0
    rows = session.scalars(
        select(TradingViewAlert).order_by(TradingViewAlert.created_at.desc()).limit(limit)
    ).all()
    return {
        "configured": bool(config and config.secret_hash),
        "enabled": bool(config and config.enabled),
        "secret_hint": config.secret_hint if config else "",
        "webhook_path": WEBHOOK_PATH,
        "total": int(total),
        "trades_from_alerts": False,
        "alerts": [
            {
                "id": str(r.id),
                "received_at": r.created_at.isoformat() if r.created_at else None,
                "symbol": r.symbol,
                "action": r.action,
                "price": r.price,
                "timeframe": r.timeframe,
                "message": r.message,
            }
            for r in rows
        ],
    }


@router.post("/secret")
def make_secret(
    _: Principal = SETTINGS_WRITE,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """A new secret, shown once. The previous one stops working at once."""
    secret = tradingview.new_secret()
    config = _config(session) or TradingViewConfig()
    config.secret_hash = tradingview.hash_secret(secret)
    config.secret_hint = secret[:4]
    config.enabled = True
    session.add(config)
    session.commit()
    return {"secret": secret, "secret_hint": config.secret_hint, "shown_once": True}
