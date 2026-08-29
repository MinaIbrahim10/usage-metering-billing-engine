# Usage Metering & Billing Engine

A production-style backend service for usage metering, quota enforcement, AI-token cost calculation, and Stripe Test Mode subscription synchronization.

The system answers three core SaaS billing questions:

1. How much has this tenant used?
2. What does that usage cost?
3. Has the tenant reached its plan limits?

The implementation focuses on correctness under retries, quota boundaries, webhook replay, and subscription synchronization.

---

## Features

- Multi-tenant usage tracking
- Free and Pro subscription plans
- Monthly API-call and AI-token quotas
- Idempotent billable requests
- Duplicate usage protection at application and database levels
- Integer-only billing math
- Cached-input token pricing
- Reasoning tokens priced as output
- Monthly usage and cost rollups
- Stripe Checkout in Test Mode
- Stripe webhook signature verification
- Stripe webhook replay protection
- Free-to-Pro plan synchronization
- Background Stripe subscription reconciliation
- SQLite persistence
- Alembic database migrations
- Automated tests
- Evidence-driven verification

---

## Architecture

Client
  |
  v
FastAPI HTTP Layer
  |
  v
Service Layer
  |
  +--> Metering Service
  +--> Pricing Service
  +--> Usage Service
  +--> Stripe Service
  +--> Reconciliation Job
  |
  v
SQLAlchemy Data Layer
  |
  v
SQLite

External integration:

Stripe Test Mode
  |
  +--> Checkout
  |
  +--> Signed Webhooks
  |
  +--> Subscription API

The HTTP layer handles validation and response mapping.

Business rules live in service modules.

Persistence is handled through SQLAlchemy models.

Stripe is treated as the source of truth for payment and subscription state.

---

## Core Correctness Rules

### Idempotent metering

Each billable request carries an idempotency key.

The pair:

tenant_id + idempotency_key

is unique.

If the same request is retried, the original usage event is returned instead of creating a second event.

This is enforced by:

1. an application-level lookup
2. a database unique constraint

---

### Quota enforcement

Usage is checked before a new event is stored.

The rule is:

current monthly usage + requested usage <= plan limit

A request exactly at the boundary is accepted.

A request beyond the quota returns:

HTTP 429 Too Many Requests

Inactive or unavailable subscription access may return:

HTTP 402 Payment Required

---

### Money and token pricing

Billing calculations never use floating-point arithmetic.

Costs are represented as integer micro-units.

Token categories are priced independently:

- fresh input tokens
- cached input tokens
- output tokens
- reasoning tokens

Cached input tokens are cheaper.

Reasoning tokens are billed using the output-token price.

---

### Stripe webhook security

Stripe webhooks are accepted only after signature verification.

A forged Stripe signature returns:

HTTP 400 Bad Request

Stripe event IDs are stored uniquely so replayed webhook events are processed only once.

---

## Plans

### Free

- 1,000 API calls per month
- 100,000 AI tokens per month

### Pro

- 10,000 API calls per month
- 2,000,000 AI tokens per month

The Stripe Test Mode Pro subscription used during development is configured separately through an environment variable.

---

## Requirements

- Python 3.13+
- Stripe CLI
- Stripe Test Mode account

Everything can be run without real payments.

---

## Setup

Clone the repository:

git clone <repository-url>
cd flyrank-capstone-metering-billing

Create a virtual environment:

python3.13 -m venv .venv
source .venv/bin/activate

Install dependencies:

pip install -r requirements.txt

Copy the environment template:

cp .env.example .env

Configure:

DATABASE_URL=sqlite:///./billing.db
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID_PRO=price_...

Never commit `.env`.

---

## Database Setup

Create the schema using Alembic:

alembic upgrade head

Seed demo plans and tenant data:

python -m app.db.seed

The seed creates:

- Free plan
- Pro plan
- Demo Tenant
- active Free subscription

---

## Run

Start the API:

uvicorn app.main:app --host 127.0.0.1 --port 8000

The service is available at:

http://127.0.0.1:8000

Swagger UI:

http://127.0.0.1:8000/docs

---

## Endpoints

### Health

GET /health

Example response:

{
  "status": "ok"
}

---

### Usage summary

GET /usage/{tenant_id}

Returns:

- tenant
- current plan
- subscription status
- monthly API-call usage
- monthly AI-token usage
- limits for both usage categories
- remaining usage
- accumulated AI-token cost

---

### Billable action

POST /generate

Example request:

{
  "tenant_id": 1,
  "idempotency_key": "request-001",
  "input_tokens": 1000,
  "cached_input_tokens": 200,
  "output_tokens": 500,
  "reasoning_tokens": 100
}

The request:

- validates input
- detects retries
- checks subscription state
- checks quota
- calculates cost
- stores one usage event

---

### Create Stripe Checkout

POST /billing/checkout/{tenant_id}

Creates a Stripe Test Mode subscription Checkout session for the Pro plan.

The tenant ID is attached to Stripe metadata so the webhook can synchronize the correct tenant after Checkout.

---

### Stripe webhook

POST /webhooks/stripe

Supported subscription-related events:

- checkout.session.completed
- customer.subscription.updated
- customer.subscription.deleted

The endpoint:

- verifies Stripe signatures
- rejects forged events
- deduplicates event IDs
- synchronizes local subscription state

---

### Background reconciliation

POST /billing/reconcile/{subscription_id}

Schedules a background reconciliation job.

The job:

- retrieves the subscription from Stripe
- compares it with local state
- updates status if needed
- retries Stripe failures up to three times
- logs a final failure if retries are exhausted

---

## Stripe Local Development

Start the FastAPI application:

uvicorn app.main:app --host 127.0.0.1 --port 8000

In another terminal, forward Stripe webhooks:

stripe listen --forward-to localhost:8000/webhooks/stripe

Copy the generated webhook signing secret into:

STRIPE_WEBHOOK_SECRET

Restart FastAPI after changing environment variables.

---

## Stripe Test Checkout

Create a Checkout session:

curl -X POST http://127.0.0.1:8000/billing/checkout/1

Open the returned Checkout URL.

Use Stripe's Test Mode card:

4242 4242 4242 4242

Use any future expiry date and a test CVC such as:

123

No real money is transferred.

After successful Checkout, Stripe sends a signed webhook and the local tenant is synchronized from Free to Pro.

---

## Tests

Run:

python -m pytest -q

Current verified result:

16 passed

The automated suite covers:

- pinned integer pricing profile
- fresh-input, cached-input, output, and reasoning-token pricing
- invalid token counts
- idempotent usage recording
- duplicate request protection
- AI-token quota boundary
- API-call quota boundary
- request validation
- tenant usage isolation
- forged Stripe webhook rejection
- Stripe webhook replay protection
- Stripe Checkout upgrade processing
- subscription.updated synchronization
- subscription.deleted synchronization
- background reconciliation retry and failure handling

Concrete runtime and acceptance evidence is documented in:

EVIDENCE.md

---

## Database Migrations

Alembic is used for versioned schema management.

Apply migrations:

alembic upgrade head

The initial migration creates:

- plans
- tenants
- subscriptions
- usage_events
- stripe_events

including the required indexes and unique constraints.

Later migrations add API-call metering and the composite monthly-rollup index:

tenant_id + created_at

Normal application startup does not create tables automatically; schema creation is migration-driven through Alembic.

---

## Evidence

See:

EVIDENCE.md

It contains observed proof for:

- duplicate request protection
- monthly usage rollup
- quota boundary behavior
- quota rejection
- pricing calculations
- Stripe Checkout
- Free-to-Pro synchronization
- forged webhook rejection
- webhook replay protection
- tenant isolation
- background reconciliation

---

## AI-Assisted Development

AI tools were used during implementation for planning, drafting, debugging, testing ideas, and documentation.

The actual runtime behavior was tested locally.

Known AI-assisted mistakes and corrections are documented honestly in:

BUILDLOG.md

---

## Limitations

The project intentionally keeps the billing scope small.

It does not implement:

- real Stripe Live Mode payments
- invoicing
- proration
- overage billing
- multi-currency billing
- real LLM inference
- distributed queues
- Redis
- production deployment
- production authentication

AI-token counts are simulated because the focus of this project is metering, billing correctness, and subscription synchronization.

Stripe is used only in Test Mode.

---

## Project Files

README.md
    Project overview, architecture, setup, and usage.

DESIGN.md
    Initial design, data model, API surface, and non-goals.

EVIDENCE.md
    Concrete evidence for implemented requirements.

BUILDLOG.md
    Honest AI-assisted development log and corrections.

capstone.yaml
    Machine-readable run, seed, test, and endpoint information.

.env.example
    Safe environment variable template.

migrations/
    Alembic database migrations.

tests/
    Automated pricing, metering, Stripe, quota, isolation, and reconciliation tests.

---

## Final Verification Commands

Install:

pip install -r requirements.txt

Create schema:

alembic upgrade head

Seed:

python -m app.db.seed

Test:

python -m pytest -q

Run:

uvicorn app.main:app --host 127.0.0.1 --port 8000
