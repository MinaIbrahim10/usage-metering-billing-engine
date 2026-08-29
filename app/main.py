from fastapi import FastAPI

from app.db.base import Base
from app.db.session import engine
import app.models  # noqa: F401

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Usage Metering & Billing Engine",
    version="0.1.0",
)


@app.get("/health")
def health():
    return {"status": "ok"}
