import os
from pathlib import Path

TEST_DB = Path("test_billing.db")

if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["DATABASE_URL"] = "sqlite:///./test_billing.db"

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.main import app
from app.models import Plan, Subscription, Tenant, UsageEvent


client = TestClient(app)


def setup_module():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    free = Plan(
        name="Free",
        api_call_limit=1000,
        ai_token_limit=100_000,
    )

    db.add(free)
    db.commit()
    db.refresh(free)

    tenant = Tenant(name="Test Tenant")
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

    if TEST_DB.exists():
        TEST_DB.unlink()


def test_duplicate_request_creates_one_event():
    payload = {
        "tenant_id": 1,
        "idempotency_key": "test-duplicate",
        "input_tokens": 1000,
        "cached_input_tokens": 200,
        "output_tokens": 500,
        "reasoning_tokens": 100,
    }

    first = client.post("/generate", json=payload)
    second = client.post("/generate", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200

    first_body = first.json()
    second_body = second.json()

    assert first_body["duplicate"] is False
    assert second_body["duplicate"] is True

    assert (
        first_body["usage_event_id"]
        == second_body["usage_event_id"]
    )

    db = SessionLocal()

    events = db.scalars(
        select(UsageEvent).where(
            UsageEvent.idempotency_key == "test-duplicate"
        )
    ).all()

    db.close()

    assert len(events) == 1


def test_exact_quota_boundary_is_allowed():
    payload = {
        "tenant_id": 1,
        "idempotency_key": "fill-to-limit",
        "input_tokens": 98_400,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
    }

    response = client.post("/generate", json=payload)

    assert response.status_code == 200

    usage = client.get("/usage/1")

    assert usage.status_code == 200

    body = usage.json()

    assert body["ai_tokens"]["used"] == 100_000
    assert body["ai_tokens"]["remaining"] == 0


def test_request_after_quota_returns_429():
    payload = {
        "tenant_id": 1,
        "idempotency_key": "over-limit",
        "input_tokens": 1,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
    }

    response = client.post("/generate", json=payload)

    assert response.status_code == 429

    body = response.json()

    assert body["detail"]["message"] == "AI token quota exceeded"
    assert body["detail"]["used"] == 100_000
    assert body["detail"]["requested"] == 1
    assert body["detail"]["limit"] == 100_000


def test_negative_tokens_are_rejected_at_boundary():
    payload = {
        "tenant_id": 1,
        "idempotency_key": "negative-test",
        "input_tokens": -1,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
    }

    response = client.post("/generate", json=payload)

    assert response.status_code == 422


def test_tenant_usage_is_isolated():
    db = SessionLocal()

    free_plan = db.scalar(
        select(Plan).where(Plan.name == "Free")
    )

    tenant_two = Tenant(name="Second Test Tenant")
    db.add(tenant_two)
    db.commit()
    db.refresh(tenant_two)

    subscription = Subscription(
        tenant_id=tenant_two.id,
        plan_id=free_plan.id,
        status="active",
    )

    db.add(subscription)
    db.commit()

    tenant_two_id = tenant_two.id
    db.close()

    payload = {
        "tenant_id": tenant_two_id,
        "idempotency_key": "tenant-two-request",
        "input_tokens": 500,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
    }

    response = client.post("/generate", json=payload)

    assert response.status_code == 200

    tenant_one_usage = client.get("/usage/1")
    tenant_two_usage = client.get(
        f"/usage/{tenant_two_id}"
    )

    assert tenant_one_usage.status_code == 200
    assert tenant_two_usage.status_code == 200

    tenant_one_body = tenant_one_usage.json()
    tenant_two_body = tenant_two_usage.json()

    assert tenant_one_body["ai_tokens"]["used"] == 100_000
    assert tenant_two_body["ai_tokens"]["used"] == 500

    assert (
        tenant_one_body["tenant_id"]
        != tenant_two_body["tenant_id"]
    )
