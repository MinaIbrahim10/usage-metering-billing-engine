from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Subscription, Tenant, UsageEvent


def _month_start() -> datetime:
    now = datetime.now(UTC).replace(tzinfo=None)
    return datetime(now.year, now.month, 1)


def get_usage_summary(db: Session, tenant_id: int) -> dict:
    tenant = db.get(Tenant, tenant_id)

    if tenant is None:
        raise HTTPException(
            status_code=404,
            detail="Tenant not found",
        )

    subscription = db.scalar(
        select(Subscription).where(
            Subscription.tenant_id == tenant_id
        )
    )

    if subscription is None:
        raise HTTPException(
            status_code=402,
            detail="Tenant has no subscription",
        )

    plan = subscription.plan

    totals = db.execute(
        select(
            func.coalesce(func.sum(UsageEvent.quantity), 0),
            func.coalesce(func.sum(UsageEvent.cost_micro_units), 0),
        ).where(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.usage_type == "ai_tokens",
            UsageEvent.created_at >= _month_start(),
        )
    ).one()

    used_tokens = int(totals[0] or 0)
    total_cost = int(totals[1] or 0)

    return {
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "plan": plan.name,
        "subscription_status": subscription.status,
        "ai_tokens": {
            "used": used_tokens,
            "limit": plan.ai_token_limit,
            "remaining": max(plan.ai_token_limit - used_tokens, 0),
        },
        "cost_micro_units": total_cost,
    }
