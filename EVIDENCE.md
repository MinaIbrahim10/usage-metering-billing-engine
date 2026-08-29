# Usage Metering & Billing Engine — Evidence

This document maps the implemented system behavior to the capstone requirements and acceptance probes.

All evidence below comes from executed automated tests, local curl smoke tests, Stripe Test Mode, or database/migration verification.

---

## 1. Idempotent Billable Metering

A billable `/generate` request was sent with:

{
  "tenant_id": 1,
  "idempotency_key": "cleanroom-smoke-001",
  "input_tokens": 1000,
  "cached_input_tokens": 200,
  "output_tokens": 500,
  "reasoning_tokens": 100
}

First response:

{
  "usage_event_id": 1,
  "tenant_id": 1,
  "idempotency_key": "cleanroom-smoke-001",
  "total_tokens": 1600,
  "cost_micro_units": 3250,
  "duplicate": false
}

The exact same request was sent again with the same idempotency key.

Second response:

{
  "usage_event_id": 1,
  "tenant_id": 1,
  "idempotency_key": "cleanroom-smoke-001",
  "total_tokens": 1600,
  "cost_micro_units": 3250,
  "duplicate": true
}

Result:

- Same usage_event_id returned
- No second usage event created
- API usage was counted once
- AI-token usage was counted once
- Cost was counted once

This proves retry-safe exactly-once metering for one tenant and idempotency key.

---

## 2. Usage Rollup

Before the clean-room billable request:

{
  "tenant_id": 1,
  "tenant_name": "Demo Tenant",
  "plan": "Free",
  "subscription_status": "active",
  "api_calls": {
    "used": 0,
    "limit": 1000,
    "remaining": 1000
  },
  "ai_tokens": {
    "used": 0,
    "limit": 100000,
    "remaining": 100000
  },
  "cost_micro_units": 0
}

After the billable request was sent twice using the same idempotency key:

{
  "tenant_id": 1,
  "tenant_name": "Demo Tenant",
  "plan": "Free",
  "subscription_status": "active",
  "api_calls": {
    "used": 1,
    "limit": 1000,
    "remaining": 999
  },
  "ai_tokens": {
    "used": 1600,
    "limit": 100000,
    "remaining": 98400
  },
  "cost_micro_units": 3250
}

The retry did not increase any usage totals.

---

## 3. AI-Token Quota Boundary

Free plan AI-token quota:

100000 tokens/month

Existing usage:

1600 tokens

A request containing exactly the remaining:

98400 tokens

was accepted.

Result:

1600 + 98400 = 100000

Usage at the exact quota boundary:

{
  "used": 100000,
  "limit": 100000,
  "remaining": 0
}

The boundary request succeeded.

One additional AI token was then requested.

Response:

HTTP 429 Too Many Requests

{
  "detail": {
    "message": "AI token quota exceeded",
    "used": 100000,
    "requested": 1,
    "limit": 100000
  }
}

This proves exact AI-token quota enforcement.

---

## 4. API-Call Quota Boundary

Free plan API-call quota:

1000 calls/month

The automated test preloaded:

999 API calls

Call number 1000:

HTTP 200 OK

Usage:

{
  "used": 1000,
  "limit": 1000,
  "remaining": 0
}

Call number 1001:

HTTP 429 Too Many Requests

{
  "detail": {
    "message": "API call quota exceeded",
    "used": 1000,
    "requested": 1,
    "limit": 1000
  }
}

This proves:

- the exact API-call boundary is allowed
- usage beyond the boundary is rejected
- the quota message contains used, requested, and limit values

---

## 5. Subscription / Payment Boundary

The metering service checks the tenant subscription before allowing a billable action.

A missing or inactive subscription produces:

HTTP 402 Payment Required

This behavior is implemented separately from HTTP 429 usage-quota failures.

---

## 6. AI Token Pricing

Pinned pricing profile:

capstone-v1

Currency:

USD

Money representation:

1 USD = 1,000,000 integer micro-units

Pinned rates:

- Fresh input: $1.00 / 1M tokens
- Cached input: $0.25 / 1M tokens
- Output: $4.00 / 1M tokens
- Reasoning: billed at the output-token rate

Test usage:

input_tokens = 1000
cached_input_tokens = 200
output_tokens = 500
reasoning_tokens = 100

Fresh input:

1000 - 200 = 800

Fresh input cost:

800 × 1,000,000 / 1,000,000 = 800 micro-units

Cached input cost:

200 × 250,000 / 1,000,000 = 50 micro-units

Output cost:

500 × 4,000,000 / 1,000,000 = 2000 micro-units

Reasoning cost:

100 × 4,000,000 / 1,000,000 = 400 micro-units

Total:

800 + 50 + 2000 + 400 = 3250 micro-units

Observed API result:

{
  "cost_micro_units": 3250
}

The implementation uses integer arithmetic only.

The automated pricing tests also verify:

- cached input cannot exceed total input
- negative token values are rejected
- reasoning tokens use the output rate
- the pricing profile and integer units are pinned

---

## 7. Stripe Test Checkout — Free to Pro

A real Stripe Checkout session was completed in Stripe Test Mode for the demo tenant.

Before Checkout:

plan = Free
AI token limit = 100000

Stripe delivered a signed:

checkout.session.completed

event to:

POST /webhooks/stripe

After the verified webhook was processed:

{
  "tenant_id": 1,
  "tenant_name": "Demo Tenant",
  "plan": "Pro",
  "subscription_status": "active",
  "ai_tokens": {
    "used": 100000,
    "limit": 2000000,
    "remaining": 1900000
  },
  "cost_micro_units": 101650
}

Result:

Free -> Pro

This proves that Stripe Test Checkout and the verified webhook synchronize the local subscription plan.

---

## 8. Stripe Webhook Signature Verification

A valid Stripe CLI webhook was accepted.

A forged request using an invalid Stripe-Signature header returned:

HTTP 400 Bad Request

{
  "detail": "Invalid Stripe webhook signature"
}

Automated test:

test_forged_webhook_returns_400

This proves forged Stripe events are rejected before subscription state is changed.

---

## 9. Stripe Webhook Replay Protection

The same Stripe event ID was processed twice.

First result:

{
  "duplicate": false
}

Second result:

{
  "duplicate": true
}

Database verification showed only one StripeEvent row for the event ID.

Automated test:

test_duplicate_stripe_event_is_ignored

This proves Stripe retries do not repeat billing-side effects.

---

## 10. Stripe Subscription Lifecycle

The automated suite covers the required Stripe subscription lifecycle.

checkout.session.completed:

test_checkout_webhook_upgrades_tenant_to_pro

Verified behavior:

- Free plan changes to Pro
- subscription remains active
- Stripe customer ID is stored
- Stripe subscription ID is stored

customer.subscription.updated:

test_subscription_updated_syncs_status

Verified behavior:

active -> past_due

customer.subscription.deleted:

test_subscription_deleted_marks_subscription_canceled

Verified behavior:

active -> canceled

This proves the local database mirrors Stripe subscription lifecycle events.

---

## 11. Tenant Isolation

A second tenant was created with its own Free subscription and usage.

Observed usage:

Tenant 1:

100000 AI tokens

Tenant 2:

500 AI tokens

The two usage summaries remained independent.

Automated tenant-isolation tests verify that usage aggregation is always filtered by tenant_id.

This proves one tenant cannot inherit another tenant's usage totals.

---

## 12. Real Persistence and Migrations

The database schema is managed using Alembic migrations.

Migration chain:

3fe6111b1acb
-> f3f66778feab
-> b42b7676ffa5

Latest verified revision:

b42b7676ffa5 (head)

A clean database was created from zero using:

DATABASE_URL=sqlite:///./cleanroom.db alembic upgrade head

The seed command then created:

Plans:

1 Free 1000 100000
2 Pro 10000 2000000

Tenant:

1 Demo Tenant

Subscription:

1 1 1 active

The application no longer calls Base.metadata.create_all() during normal startup.

Schema creation is migration-driven.

---

## 13. Usage Rollup Index

Monthly usage calculations filter primarily by tenant and timestamp.

The schema contains the composite index:

ix_usage_events_tenant_created

Columns:

tenant_id, created_at

Alembic migration:

b42b7676ffa5_add_usage_rollup_index.py

This supports tenant-scoped monthly usage rollups.

---

## 14. Background Subscription Reconciliation

The service includes a background reconciliation path that compares the local subscription with Stripe.

Endpoint:

POST /billing/reconcile/{subscription_id}

The reconciliation operation runs outside the request path using FastAPI BackgroundTasks.

A successful manual reconciliation against Stripe returned immediately as scheduled and later logged successful synchronization.

Failure handling is covered by:

test_reconciliation_retries_three_times_on_stripe_failure

The test simulates a Stripe outage.

Verified behavior:

- Stripe retrieval attempted 3 times
- retry delays are applied in production code
- the test replaces delays with a mock
- after the final retry the service records a permanent failure error

The automated assertion verifies exactly 3 Stripe retrieval attempts.

---

## 15. Validation at the HTTP Boundary

Pydantic request validation rejects invalid token counts before they reach billing logic.

Examples covered by tests:

- negative token counts are rejected with a 4xx validation response
- cached_input_tokens greater than input_tokens are rejected
- invalid requests do not become internal HTTP 500 errors

This proves validation occurs at the application boundary.

---

## 16. Layered Architecture

The application separates responsibilities into distinct layers:

HTTP/API layer:

app/main.py

Database/session layer:

app/db/

Persistence models:

app/models/

Request/response schemas:

app/schemas/

Metering logic:

app/services/metering.py

Usage rollups:

app/services/usage.py

Pricing logic:

app/services/pricing.py

Stripe integration:

app/services/stripe_service.py

Background reconciliation:

app/services/reconciliation.py

Database migrations:

migrations/

This keeps HTTP, business logic, pricing, persistence, and Stripe synchronization separate.

---

## 17. Clean-Room Runtime Verification

A completely new SQLite database was built using only the documented migration and seed path.

Health endpoint:

GET /health

Response:

{
  "status": "ok"
}

Initial usage:

API calls = 0
AI tokens = 0
Cost = 0

A billable request then produced:

{
  "usage_event_id": 1,
  "total_tokens": 1600,
  "cost_micro_units": 3250,
  "duplicate": false
}

Retrying the exact same request produced:

{
  "usage_event_id": 1,
  "total_tokens": 1600,
  "cost_micro_units": 3250,
  "duplicate": true
}

Final usage:

API calls = 1
AI tokens = 1600
Cost micro-units = 3250

This proves a clean database can be migrated, seeded, started, and used without relying on development database state.

---

## 18. Automated Test Suite

Final test result at this stage:

16 passed

Covered areas include:

- integer AI pricing
- cached-input pricing
- reasoning-token pricing
- pricing input validation
- pinned pricing profile
- idempotent usage metering
- AI-token quota boundary
- API-call quota boundary
- tenant isolation
- Stripe forged-signature rejection
- Stripe event replay protection
- Stripe Checkout upgrade processing
- Stripe subscription update synchronization
- Stripe subscription deletion synchronization
- reconciliation retry/failure behavior

One StarletteDeprecationWarning is emitted by the installed FastAPI/Starlette TestClient dependency stack.

It does not represent a failed application test.

---

## 19. Acceptance Probe Mapping

Probe 1 — same billable request twice:

PASS

Proof:

- Section 1
- same usage_event_id
- duplicate=false then duplicate=true
- usage counted once

Probe 2 — exact quota boundary:

PASS

Proof:

- Section 3 AI-token quota
- Section 4 API-call quota
- exact boundary accepted
- request beyond boundary returns HTTP 429

Probe 3 — Stripe Checkout Free -> Pro:

PASS

Proof:

- Section 7
- real Stripe Test Mode Checkout
- verified checkout.session.completed webhook
- GET /usage reflected Pro limits

Probe 4 — forged and replayed webhook:

PASS

Proof:

- Section 8 forged signature -> HTTP 400
- Section 9 duplicate Stripe event processed once

Probe 5 — pinned pricing rules:

PASS

Proof:

- Section 6
- cached input priced separately
- reasoning priced as output
- exact result = 3250 micro-units
- GET /usage matched the stored cost

---

## 20. Final Requirement Status

- [x] Layered architecture
- [x] Validation at the HTTP boundary
- [x] Background job
- [x] Background retries
- [x] Final background failure reporting
- [x] Database schema managed by migrations
- [x] Tenant isolation
- [x] Usage rollup index
- [x] Idempotent billable requests
- [x] API-call metering
- [x] AI-token metering
- [x] API-call quotas
- [x] AI-token quotas
- [x] HTTP 429 quota behavior
- [x] HTTP 402 subscription/payment behavior
- [x] Integer money representation
- [x] Cached-input pricing
- [x] Reasoning-token pricing
- [x] Stripe Test Checkout
- [x] Stripe signature verification
- [x] Stripe event deduplication
- [x] Stripe subscription.updated synchronization
- [x] Stripe subscription.deleted synchronization
- [x] Clean-room migration and seed verification
- [x] Automated test suite

Pending final repository-hygiene proof:

- [x] Confirm .env is ignored
- [x] Scan tracked files/history for real Stripe secrets
- [x] Final README / capstone.yaml / BUILDLOG review
- [x] Public GitHub repository verification
