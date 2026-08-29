# Usage Metering & Billing Engine — Design

## 1. Problem

This service answers three questions for a SaaS product:

1. How much has a tenant used?
2. What does that usage cost?
3. Has the tenant reached its plan limits?

The system must meter billable usage safely, enforce quotas, calculate cost using deterministic integer-based pricing rules, and synchronize subscription state from Stripe test-mode webhooks.

The most important correctness requirement is that retries must never create duplicate usage events or duplicate billing effects.

---

## 2. Scope

The core system supports:

- Multi-tenant usage tracking
- Two subscription plans: Free and Pro
- Two usage categories:
  - API calls
  - AI tokens
- One dummy billable endpoint
- Idempotent usage recording
- Monthly quota enforcement
- Cost calculation
- Stripe Checkout in test mode
- Signature-verified and deduplicated Stripe webhooks
- Usage summary per tenant

---

## 3. Explicit Non-Goals

The first version will NOT include:

- Real AI model calls
- Real payments or Stripe live mode
- Invoicing
- Proration
- Overage billing
- Usage notifications
- Multi-currency billing
- Distributed deployment
- Redis or external queues

AI token counts will be simulated because this capstone is about metering and billing correctness, not model inference.

---

## 4. Plans and Quotas

### Free

- API calls: 1,000 per month
- AI tokens: 100,000 per month

### Pro

- API calls: 10,000 per month
- AI tokens: 2,000,000 per month

All limits will be stored as configuration/data rather than hardcoded into request handlers.

---

## 5. Data Model

### Tenant

- id
- name
- created_at

### Plan

- id
- name
- api_call_limit
- ai_token_limit

### Subscription

- id
- tenant_id
- plan_id
- status
- stripe_customer_id
- stripe_subscription_id
- created_at
- updated_at

### UsageEvent

- id
- tenant_id
- usage_type
- quantity
- idempotency_key
- input_tokens
- cached_input_tokens
- output_tokens
- reasoning_tokens
- cost_micro_units
- created_at

The pair:

tenant_id + idempotency_key

must be unique so the same request cannot create two usage events.

### StripeEvent

- id
- stripe_event_id
- event_type
- processed_at

stripe_event_id must be unique so replayed Stripe webhooks are processed once.

---

## 6. API Surface

### Health

GET /health

Returns service health.

### Usage

GET /usage/{tenant_id}

Returns:

- plan
- current monthly usage
- quota limits
- calculated cost

### Billable action

POST /generate

Input includes:

- tenant_id
- idempotency_key
- token usage values

Flow:

1. Validate tenant and request
2. Detect duplicate idempotency key
3. Calculate requested usage
4. Check quota
5. Calculate cost
6. Store exactly one usage event
7. Return the original result on retry

### Stripe Checkout

POST /billing/checkout/{tenant_id}

Creates a Stripe Checkout session for upgrading to Pro.

### Stripe webhook

POST /webhooks/stripe

Flow:

1. Verify Stripe signature
2. Reject forged events
3. Detect duplicate Stripe event ID
4. Process supported subscription event
5. Update local subscription state
6. Mark Stripe event as processed

---

## 7. Layered Architecture

Client
  |
  v
FastAPI HTTP Layer
  |
  v
Service Layer
  |
  +--> Metering Service
  +--> Quota Service
  +--> Pricing Service
  +--> Billing / Stripe Service
  |
  v
Repository / Data Layer
  |
  v
SQLite Database

The HTTP layer validates requests and maps errors to HTTP responses.

The service layer contains business rules.

The repository/data layer handles persistence only.

Stripe is treated as the source of truth for payment/subscription state.

---

## 8. Idempotency Strategy

For billable requests:

- Every request includes an idempotency key.
- The database enforces uniqueness on tenant_id + idempotency_key.
- If the same key is received again for the same tenant, the service returns the original stored result.
- No second usage event is created.

This protects against client retries and network retries.

---

## 9. Quota Strategy

Before recording usage:

current_month_usage + requested_usage <= plan_limit

If usage would exceed the allowed quota:

- return 429 for usage quota exhaustion
- return 402 when access is blocked because of subscription/payment state

The response must contain a clear JSON error message.

---

## 10. Pricing Strategy

All money values are stored as integer micro-units.

Never use floating-point arithmetic for billing calculations.

AI token categories are priced separately:

- fresh input tokens
- cached input tokens
- output tokens
- reasoning tokens

Reasoning tokens use the output-token price.

Cached input tokens use a lower input-token price.

Pricing constants will live in configuration and exact example calculations will be recorded in EVIDENCE.md.

---

## 11. Stripe Strategy

Stripe test mode only.

The application will:

- create Checkout sessions
- verify webhook signatures
- process:
  - checkout.session.completed
  - customer.subscription.updated
  - customer.subscription.deleted
- ignore duplicate webhook events safely

Secrets will only be loaded from environment variables and will never be committed.

---

## 12. Evidence Strategy

EVIDENCE.md will contain proof for:

1. Same idempotency key sent twice -> one usage event
2. Exact quota boundary behavior
3. Request after quota -> 429 or 402 with clear message
4. Correct token pricing totals
5. Stripe Checkout Free -> Pro
6. Forged webhook -> 400
7. Replayed valid webhook -> processed once
8. Tenant usage isolation

---

## 13. Initial Technology Choice

- Python 3.13+
- FastAPI
- SQLAlchemy
- SQLite
- Alembic
- Stripe Python SDK
- Pydantic
- Uvicorn
- Pytest
