from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Subscription, Tenant, UsageEvent
from app.schemas.schemas import GenerateRequest
from app.services.pricing import TokenUsage, calculate_token_cost


def _month_start() -> datetime:
    now = datetime.now(UTC).replace(tzinfo=None)
    return datetime(now.year, now.month, 1)


def record_usage(
    db: Session,
    request: GenerateRequest,
) -> tuple[UsageEvent, bool]:
    # 1. Tenant must exist.
    tenant = db.get(Tenant, request.tenant_id)

    if tenant is None:
        raise HTTPException(
            status_code=404,
            detail="Tenant not found",
        )

    # 2. Same idempotency key = same already-recorded operation.
    existing = db.scalar(
        select(UsageEvent).where(
            UsageEvent.tenant_id == request.tenant_id,
            UsageEvent.idempotency_key == request.idempotency_key,
        )
    )

    if existing is not None:
        return existing, True

    # 3. Tenant needs an active subscription + plan.
    subscription = db.scalar(
        select(Subscription).where(
            Subscription.tenant_id == request.tenant_id
        )
    )

    if subscription is None:
        raise HTTPException(
            status_code=402,
            detail="Tenant has no subscription",
        )

    if subscription.status != "active":
        raise HTTPException(
            status_code=402,
            detail="Subscription is not active",
        )

    plan = subscription.plan

    # 4. Calculate token quantities for this request.
    total_requested_tokens = (
        request.input_tokens
        + request.output_tokens
        + request.reasoning_tokens
    )

    # cached_input_tokens is a subset of input_tokens,
    # so it must NOT be added again to total usage.
    if request.cached_input_tokens > request.input_tokens:
        raise HTTPException(
            status_code=422,
            detail="cached_input_tokens cannot exceed input_tokens",
        )

    # 5. Current monthly AI-token usage.
    current_tokens = db.scalar(
        select(
            func.coalesce(func.sum(UsageEvent.quantity), 0)
        ).where(
            UsageEvent.tenant_id == request.tenant_id,
            UsageEvent.usage_type == "ai_tokens",
            UsageEvent.created_at >= _month_start(),
        )
    )

    current_tokens = int(current_tokens or 0)

    # Current monthly API-call usage.
    current_api_calls = db.scalar(
        select(
            func.coalesce(func.sum(UsageEvent.api_calls), 0)
        ).where(
            UsageEvent.tenant_id == request.tenant_id,
            UsageEvent.created_at >= _month_start(),
        )
    )

    current_api_calls = int(current_api_calls or 0)

    # Each /generate request counts as one API call.
    if current_api_calls + 1 > plan.api_call_limit:
        raise HTTPException(
            status_code=429,
            detail={
                "message": "API call quota exceeded",
                "used": current_api_calls,
                "requested": 1,
                "limit": plan.api_call_limit,
            },
        )

    # 6. Enforce quota BEFORE storing the event.
    if current_tokens + total_requested_tokens > plan.ai_token_limit:
        raise HTTPException(
            status_code=429,
            detail={
                "message": "AI token quota exceeded",
                "used": current_tokens,
                "requested": total_requested_tokens,
                "limit": plan.ai_token_limit,
            },
        )

    # 7. Calculate billing cost.
    try:
        cost = calculate_token_cost(
            TokenUsage(
                input_tokens=request.input_tokens,
                cached_input_tokens=request.cached_input_tokens,
                output_tokens=request.output_tokens,
                reasoning_tokens=request.reasoning_tokens,
            )
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    # 8. Save exactly one usage event.
    event = UsageEvent(
        tenant_id=request.tenant_id,
        usage_type="ai_tokens",
        quantity=total_requested_tokens,
        api_calls=1,
        idempotency_key=request.idempotency_key,
        input_tokens=request.input_tokens,
        cached_input_tokens=request.cached_input_tokens,
        output_tokens=request.output_tokens,
        reasoning_tokens=request.reasoning_tokens,
        cost_micro_units=cost,
    )

    db.add(event)

    try:
        db.commit()
        db.refresh(event)

    except IntegrityError:
        # Protect against two identical requests arriving concurrently.
        db.rollback()

        existing = db.scalar(
            select(UsageEvent).where(
                UsageEvent.tenant_id == request.tenant_id,
                UsageEvent.idempotency_key == request.idempotency_key,
            )
        )

        if existing is None:
            raise

        return existing, True

    return event, False
