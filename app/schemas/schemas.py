from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    tenant_id: int = Field(gt=0)
    idempotency_key: str = Field(min_length=1, max_length=160)

    input_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)


class GenerateResponse(BaseModel):
    usage_event_id: int
    tenant_id: int
    idempotency_key: str
    total_tokens: int
    cost_micro_units: int
    duplicate: bool
