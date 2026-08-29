from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Plan, Subscription, Tenant


def seed():
    db = SessionLocal()

    try:
        free_plan = db.scalar(
            select(Plan).where(Plan.name == "Free")
        )

        if free_plan is None:
            free_plan = Plan(
                name="Free",
                api_call_limit=1000,
                ai_token_limit=100_000,
            )
            db.add(free_plan)

        pro_plan = db.scalar(
            select(Plan).where(Plan.name == "Pro")
        )

        if pro_plan is None:
            pro_plan = Plan(
                name="Pro",
                api_call_limit=10_000,
                ai_token_limit=2_000_000,
            )
            db.add(pro_plan)

        db.commit()

        demo_tenant = db.scalar(
            select(Tenant).where(Tenant.name == "Demo Tenant")
        )

        if demo_tenant is None:
            demo_tenant = Tenant(name="Demo Tenant")
            db.add(demo_tenant)
            db.commit()
            db.refresh(demo_tenant)

        existing_subscription = db.scalar(
            select(Subscription).where(
                Subscription.tenant_id == demo_tenant.id
            )
        )

        if existing_subscription is None:
            subscription = Subscription(
                tenant_id=demo_tenant.id,
                plan_id=free_plan.id,
                status="active",
            )
            db.add(subscription)
            db.commit()

        print("Seed complete")
        print(f"Tenant ID: {demo_tenant.id}")
        print(f"Tenant: {demo_tenant.name}")
        print(f"Plan: {free_plan.name}")

    finally:
        db.close()


if __name__ == "__main__":
    seed()
