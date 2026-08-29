# Usage Metering & Billing Engine — Evidence

This document contains concrete proof for the capstone requirements.

---

## 1. Metering — Idempotency

### First request

Request:

{
  "tenant_id": 1,
  "idempotency_key": "demo-request-001",
  "input_tokens": 1000,
  "cached_input_tokens": 200,
  "output_tokens": 500,
  "reasoning_tokens": 100
}

Response:

{
  "usage_event_id": 1,
  "tenant_id": 1,
  "idempotency_key": "demo-request-001",
  "total_tokens": 1600,
  "cost_micro_units": 3250,
  "duplicate": false
}

### Same request retried with the same idempotency key

Request:

{
  "tenant_id": 1,
  "idempotency_key": "demo-request-001",
  "input_tokens": 1000,
  "cached_input_tokens": 200,
  "output_tokens": 500,
  "reasoning_tokens": 100
}

Response:

{
  "usage_event_id": 1,
  "tenant_id": 1,
  "idempotency_key": "demo-request-001",
  "total_tokens": 1600,
  "cost_micro_units": 3250,
  "duplicate": true
}

Result:

usage_event_id = 1

The second request returned the original usage event.
No second usage event was created.

This proves that retries using the same tenant and idempotency key do not double-count usage.

---

## 2. Monthly Usage Summary

After the first successful billable request:

{
  "tenant_id": 1,
  "tenant_name": "Demo Tenant",
  "plan": "Free",
  "subscription_status": "active",
  "ai_tokens": {
    "used": 1600,
    "limit": 100000,
    "remaining": 98400
  },
  "cost_micro_units": 3250
}

The duplicate retry did not increase usage from 1600 to 3200.

---

## 3. Quota Boundary

The Free plan has the following monthly AI-token quota:

100000 tokens/month

Before the boundary test:

{
  "used": 1600,
  "limit": 100000,
  "remaining": 98400
}

A new request was sent containing exactly the remaining 98400 tokens.

Request:

{
  "tenant_id": 1,
  "idempotency_key": "quota-fill-001",
  "input_tokens": 98400,
  "cached_input_tokens": 0,
  "output_tokens": 0,
  "reasoning_tokens": 0
}

Response:

{
  "usage_event_id": 2,
  "tenant_id": 1,
  "idempotency_key": "quota-fill-001",
  "total_tokens": 98400,
  "cost_micro_units": 98400,
  "duplicate": false
}

Usage after the request:

{
  "tenant_id": 1,
  "tenant_name": "Demo Tenant",
  "plan": "Free",
  "subscription_status": "active",
  "ai_tokens": {
    "used": 100000,
    "limit": 100000,
    "remaining": 0
  },
  "cost_micro_units": 101650
}

Result:

1600 + 98400 = 100000

The exact quota boundary was accepted successfully.

---

## 4. Quota Exceeded

After the tenant reached exactly 100000 tokens, one additional token was requested.

Request:

{
  "tenant_id": 1,
  "idempotency_key": "over-quota-001",
  "input_tokens": 1,
  "cached_input_tokens": 0,
  "output_tokens": 0,
  "reasoning_tokens": 0
}

Response status:

HTTP/1.1 429 Too Many Requests

Response body:

{
  "detail": {
    "message": "AI token quota exceeded",
    "used": 100000,
    "requested": 1,
    "limit": 100000
  }
}

The service allows usage exactly at the documented quota boundary and rejects usage beyond the quota with a clear HTTP 429 response.

---

## 5. AI Token Pricing

The pricing engine handles token categories separately.

Test input:

input_tokens        = 1000
cached_input_tokens = 200
output_tokens       = 500
reasoning_tokens    = 100

Fresh input tokens:

1000 - 200 = 800

Output-priced tokens:

500 + 100 = 600

Using the pinned demo pricing constants:

Fresh input:
800 × 1,000,000 / 1,000,000 = 800 micro-units

Cached input:
200 × 250,000 / 1,000,000 = 50 micro-units

Output + reasoning:
600 × 4,000,000 / 1,000,000 = 2400 micro-units

Total:

800 + 50 + 2400 = 3250 micro-units

Observed API response:

{
  "cost_micro_units": 3250
}

All billing calculations use integer arithmetic rather than floating-point money calculations.

---

## 6. Pricing Validation Tests

The pricing test suite currently verifies:

- correct fresh-input pricing
- lower cached-input pricing
- reasoning tokens billed as output
- cached input cannot exceed total input
- negative token counts are rejected

Test result:

3 passed in 0.01s

---

## 7. Current Evidence Status

Completed evidence:

- [x] Idempotent billable request
- [x] Duplicate request creates no second usage event
- [x] Monthly usage rollup
- [x] Exact quota boundary accepted
- [x] Usage beyond quota returns HTTP 429
- [x] Cached input priced separately
- [x] Reasoning tokens priced as output
- [x] Integer-only cost calculation
- [x] Pricing validation tests

Still to be added:

- [ ] Stripe test Checkout changes tenant from Free to Pro
- [ ] Stripe webhook signature verification
- [ ] Forged Stripe webhook returns HTTP 400
- [ ] Replayed Stripe webhook is processed only once
- [ ] Tenant isolation proof
- [ ] Final automated acceptance tests

---

## 8. Stripe Test Checkout — Free to Pro

A real Stripe Checkout session was created in Test Mode for tenant 1.

The checkout used a Stripe test card and completed successfully.

After successful Checkout, Stripe sent a signed:

checkout.session.completed

webhook to:

POST /webhooks/stripe

The webhook was verified and processed by the backend.

Before Checkout:

plan = Free
AI token limit = 100000

After Checkout:

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

This proves that Stripe Checkout and the signed webhook synchronize the tenant subscription state correctly.

---

## 9. Stripe Webhook Signature Verification

A valid Stripe webhook delivered through Stripe CLI returned:

HTTP 200 OK

A manually forged webhook using:

Stripe-Signature: fake-signature

returned:

HTTP/1.1 400 Bad Request

{
  "detail": "Invalid Stripe webhook signature"
}

This proves that unverified callers cannot forge Stripe subscription events.

---

## 10. Stripe Webhook Replay Protection

The same Stripe event ID was processed twice:

First result:

{
  "received": true,
  "duplicate": false,
  "event_id": "evt_replay_test_001",
  "event_type": "product.created"
}

Second result:

{
  "received": true,
  "duplicate": true,
  "event_id": "evt_replay_test_001",
  "event_type": "product.created"
}

The second delivery was detected as a duplicate and was not processed again.

This proves that webhook retries do not cause duplicate billing-side effects.

---

## 11. Tenant Isolation

A second tenant was created with its own active Free subscription.

Tenant 1 usage:

100000 AI tokens

Tenant 2 usage:

500 AI tokens

The usage summary for each tenant remained independent.

Result:

Tenant 1 -> 100000 used
Tenant 2 -> 500 used

Tenant 2 did not inherit or include Tenant 1 usage.

This proves that usage events, quota calculations, and usage summaries are isolated by tenant.
