from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.db.base import Base
from app.db.deps import get_db
from app.db.session import engine
from app.schemas.schemas import GenerateRequest, GenerateResponse
from app.services.metering import record_usage
from app.services.usage import get_usage_summary

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Usage Metering & Billing Engine",
    version="0.1.0",
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/usage/{tenant_id}")
def usage(
    tenant_id: int,
    db: Session = Depends(get_db),
):
    return get_usage_summary(db, tenant_id)


@app.post(
    "/generate",
    response_model=GenerateResponse,
)
def generate(
    request: GenerateRequest,
    db: Session = Depends(get_db),
):
    event, duplicate = record_usage(db, request)

    return GenerateResponse(
        usage_event_id=event.id,
        tenant_id=event.tenant_id,
        idempotency_key=event.idempotency_key,
        total_tokens=event.quantity,
        cost_micro_units=event.cost_micro_units,
        duplicate=duplicate,
    )
