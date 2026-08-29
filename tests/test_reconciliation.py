from unittest.mock import patch

import stripe

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import Plan, Subscription, Tenant
from app.services.reconciliation import reconcile_subscription


def setup_module():
    engine.dispose()

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    pro = Plan(
        name="Pro",
        api_call_limit=10_000,
        ai_token_limit=2_000_000,
    )

    db.add(pro)
    db.commit()
    db.refresh(pro)

    tenant = Tenant(
        name="Reconciliation Test Tenant",
    )

    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    subscription = Subscription(
        tenant_id=tenant.id,
        plan_id=pro.id,
        status="active",
        stripe_customer_id="cus_test_reconciliation",
        stripe_subscription_id="sub_test_reconciliation",
    )

    db.add(subscription)
    db.commit()
    db.close()


def teardown_module():
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_reconciliation_retries_three_times_on_stripe_failure(
    caplog,
):
    stripe_error = stripe.APIConnectionError(
        message="Simulated Stripe outage"
    )

    with patch(
        "app.services.reconciliation.stripe.Subscription.retrieve",
        side_effect=stripe_error,
    ) as mocked_retrieve:
        with patch(
            "app.services.reconciliation.time.sleep",
            return_value=None,
        ):
            reconcile_subscription(
                subscription_id=1,
                max_attempts=3,
            )

    assert mocked_retrieve.call_count == 3

    messages = [
        record.getMessage()
        for record in caplog.records
    ]

    assert any(
        "Reconciliation permanently failed"
        in message
        for message in messages
    )
