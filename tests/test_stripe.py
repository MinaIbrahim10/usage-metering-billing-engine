import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.main import app
from app.models import Plan, StripeEvent, Subscription, Tenant
from app.services.stripe_service import process_stripe_event


client = TestClient(app)

TEST_DB = Path("test_billing.db")


def setup_module():
    # Close any SQLite connections left by previous test modules.
    engine.dispose()

    if TEST_DB.exists():
        TEST_DB.unlink()

    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    free = Plan(
        name="Free",
        api_call_limit=1000,
        ai_token_limit=100_000,
    )

    pro = Plan(
        name="Pro",
        api_call_limit=10_000,
        ai_token_limit=2_000_000,
    )

    db.add_all([free, pro])
    db.commit()

    tenant = Tenant(name="Stripe Test Tenant")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    subscription = Subscription(
        tenant_id=tenant.id,
        plan_id=free.id,
        status="active",
    )

    db.add(subscription)
    db.commit()
    db.close()


def teardown_module():
    Base.metadata.drop_all(bind=engine)

    # Important for SQLite before deleting the database file.
    engine.dispose()

    if TEST_DB.exists():
        TEST_DB.unlink()


def test_forged_webhook_returns_400():
    payload = {
        "id": "evt_fake",
        "type": "checkout.session.completed",
        "data": {
            "object": {}
        },
    }

    response = client.post(
        "/webhooks/stripe",
        content=json.dumps(payload),
        headers={
            "Content-Type": "application/json",
            "Stripe-Signature": "fake-signature",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Invalid Stripe webhook signature"
    )


def test_duplicate_stripe_event_is_ignored():
    db = SessionLocal()

    event = {
        "id": "evt_duplicate_test",
        "type": "product.created",
        "data": {
            "object": {}
        },
    }

    first = process_stripe_event(db, event)
    second = process_stripe_event(db, event)

    assert first["duplicate"] is False
    assert second["duplicate"] is True

    events = db.scalars(
        select(StripeEvent).where(
            StripeEvent.stripe_event_id
            == "evt_duplicate_test"
        )
    ).all()

    assert len(events) == 1

    db.close()


def test_checkout_webhook_upgrades_tenant_to_pro():
    db = SessionLocal()

    subscription_before = db.scalar(
        select(Subscription).where(
            Subscription.tenant_id == 1
        )
    )

    free_plan = db.scalar(
        select(Plan).where(Plan.name == "Free")
    )

    assert subscription_before.plan_id == free_plan.id

    event = {
        "id": "evt_checkout_upgrade_test",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "metadata": {
                    "tenant_id": "1"
                },
                "customer": "cus_test_123",
                "subscription": "sub_test_123",
            }
        },
    }

    result = process_stripe_event(db, event)

    assert result["duplicate"] is False

    db.expire_all()

    subscription_after = db.scalar(
        select(Subscription).where(
            Subscription.tenant_id == 1
        )
    )

    pro_plan = db.scalar(
        select(Plan).where(Plan.name == "Pro")
    )

    assert subscription_after.plan_id == pro_plan.id
    assert subscription_after.status == "active"
    assert subscription_after.stripe_customer_id == "cus_test_123"
    assert (
        subscription_after.stripe_subscription_id
        == "sub_test_123"
    )

    db.close()


def test_subscription_updated_syncs_status():
    db = SessionLocal()

    subscription = db.scalar(
        select(Subscription).where(
            Subscription.tenant_id == 1
        )
    )

    subscription.stripe_subscription_id = "sub_update_test"
    subscription.status = "active"
    db.commit()

    event = {
        "id": "evt_subscription_updated_test",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_update_test",
                "status": "past_due",
            }
        },
    }

    result = process_stripe_event(db, event)

    assert result["duplicate"] is False

    db.expire_all()

    updated = db.scalar(
        select(Subscription).where(
            Subscription.stripe_subscription_id
            == "sub_update_test"
        )
    )

    assert updated is not None
    assert updated.status == "past_due"

    db.close()


def test_subscription_deleted_marks_subscription_canceled():
    db = SessionLocal()

    subscription = db.scalar(
        select(Subscription).where(
            Subscription.tenant_id == 1
        )
    )

    subscription.stripe_subscription_id = "sub_delete_test"
    subscription.status = "active"
    db.commit()

    event = {
        "id": "evt_subscription_deleted_test",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_delete_test",
                "status": "canceled",
            }
        },
    }

    result = process_stripe_event(db, event)

    assert result["duplicate"] is False

    db.expire_all()

    deleted = db.scalar(
        select(Subscription).where(
            Subscription.stripe_subscription_id
            == "sub_delete_test"
        )
    )

    assert deleted is not None
    assert deleted.status == "canceled"

    db.close()
