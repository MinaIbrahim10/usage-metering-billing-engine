import stripe
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import (
    STRIPE_PRICE_ID_PRO,
    STRIPE_SECRET_KEY,
    STRIPE_WEBHOOK_SECRET,
)
from app.models import Plan, StripeEvent, Subscription, Tenant


SUPPORTED_EVENTS = {
    "checkout.session.completed",
    "customer.subscription.updated",
    "customer.subscription.deleted",
}

stripe.api_key = STRIPE_SECRET_KEY


def create_checkout_session(
    db: Session,
    tenant_id: int,
) -> dict:
    if not STRIPE_SECRET_KEY:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured")

    if not STRIPE_PRICE_ID_PRO:
        raise RuntimeError("STRIPE_PRICE_ID_PRO is not configured")

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
            status_code=404,
            detail="Subscription not found",
        )

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[
                {
                    "price": STRIPE_PRICE_ID_PRO,
                    "quantity": 1,
                }
            ],
            metadata={
                "tenant_id": str(tenant_id),
            },
            subscription_data={
                "metadata": {
                    "tenant_id": str(tenant_id),
                }
            },
            success_url=(
                "http://localhost:8000/billing/success"
                "?session_id={CHECKOUT_SESSION_ID}"
            ),
            cancel_url="http://localhost:8000/billing/cancel",
        )

    except stripe.StripeError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Stripe error: {exc.user_message or str(exc)}",
        ) from exc

    return {
        "checkout_session_id": session.id,
        "checkout_url": session.url,
        "tenant_id": tenant_id,
        "target_plan": "Pro",
    }


def construct_stripe_event(payload: bytes, signature: str):
    if not STRIPE_WEBHOOK_SECRET:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET is not configured")

    try:
        return stripe.Webhook.construct_event(
            payload=payload,
            sig_header=signature,
            secret=STRIPE_WEBHOOK_SECRET,
        )

    except (ValueError, stripe.error.SignatureVerificationError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid Stripe webhook signature",
        ) from exc


def process_stripe_event(db: Session, event) -> dict:
    event_id = event["id"]
    event_type = event["type"]

    existing = db.scalar(
        select(StripeEvent).where(
            StripeEvent.stripe_event_id == event_id
        )
    )

    if existing is not None:
        return {
            "received": True,
            "duplicate": True,
            "event_id": event_id,
            "event_type": event_type,
        }

    if event_type in SUPPORTED_EVENTS:
        stripe_object = event["data"]["object"]

        if hasattr(stripe_object, "to_dict"):
            obj = stripe_object.to_dict()
        else:
            obj = dict(stripe_object)

        if event_type == "checkout.session.completed":
            metadata = obj.get("metadata") or {}
            tenant_id = metadata.get("tenant_id")

            if tenant_id:
                subscription = db.scalar(
                    select(Subscription).where(
                        Subscription.tenant_id == int(tenant_id)
                    )
                )

                pro_plan = db.scalar(
                    select(Plan).where(
                        Plan.name == "Pro"
                    )
                )

                if subscription is not None and pro_plan is not None:
                    subscription.plan_id = pro_plan.id
                    subscription.status = "active"

                    customer_id = obj.get("customer")
                    stripe_subscription_id = obj.get("subscription")

                    if customer_id:
                        subscription.stripe_customer_id = customer_id

                    if stripe_subscription_id:
                        subscription.stripe_subscription_id = (
                            stripe_subscription_id
                        )

        elif event_type == "customer.subscription.updated":
            stripe_subscription_id = obj.get("id")

            subscription = db.scalar(
                select(Subscription).where(
                    Subscription.stripe_subscription_id
                    == stripe_subscription_id
                )
            )

            if subscription is not None:
                subscription.status = obj.get(
                    "status",
                    subscription.status,
                )

        elif event_type == "customer.subscription.deleted":
            stripe_subscription_id = obj.get("id")

            subscription = db.scalar(
                select(Subscription).where(
                    Subscription.stripe_subscription_id
                    == stripe_subscription_id
                )
            )

            if subscription is not None:
                subscription.status = "canceled"

    stripe_event = StripeEvent(
        stripe_event_id=event_id,
        event_type=event_type,
    )

    db.add(stripe_event)

    try:
        db.commit()

    except IntegrityError:
        db.rollback()

        return {
            "received": True,
            "duplicate": True,
            "event_id": event_id,
            "event_type": event_type,
        }

    return {
        "received": True,
        "duplicate": False,
        "event_id": event_id,
        "event_type": event_type,
    }
