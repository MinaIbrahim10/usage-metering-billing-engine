# Build Log

## Project

Usage Metering & Billing Engine

## AI-Assisted Development

AI tools were used during development for:

- breaking the capstone brief into implementation phases
- drafting initial FastAPI and SQLAlchemy structure
- reviewing idempotency and quota logic
- suggesting test cases
- debugging Stripe integration errors
- drafting documentation and evidence structure

## Important Corrections Made During Development

### Stripe object handling

An early webhook implementation treated a Stripe Checkout Session object like a Python dictionary and called `.get()` directly.

This caused:

AttributeError: 'get' is a dict method, but a Session is not a dict.

The implementation was corrected by converting Stripe objects with `.to_dict()` before dictionary-style access.

### Environment selection

The project was initially created with Python 3.14 because the system shell was configured for separate TensorFlow compatibility work.

The virtual environment was recreated with Python 3.13 for a more stable dependency baseline.

### Package installation

Stripe CLI installation through the AUR failed because the local Arch package database referenced an unavailable Go package version.

Instead of upgrading the whole system, the official prebuilt Stripe CLI binary was installed directly.

### Billing correctness

Usage metering is protected at two levels:

1. application-level lookup by tenant + idempotency key
2. database-level unique constraint

This avoids relying only on a pre-insert check.

## What AI Did Not Replace

All important behavior was run and verified locally.

The following were tested directly:

- FastAPI health endpoint
- database seeding
- AI-token pricing
- duplicate billable request handling
- exact quota boundary
- quota rejection
- tenant isolation
- Alembic migration creation
- clean migration upgrade
- Stripe Test Mode events
- Stripe Checkout
- signed webhook processing
- forged webhook rejection
- webhook replay protection
- Free-to-Pro subscription synchronization
- background Stripe reconciliation

The final implementation and evidence only claim behavior that was actually observed or tested.


## Later Hardening and Corrections

### API-call metering

The initial implementation correctly metered AI tokens but did not yet account for the second required usage category: API calls.

The data model and metering service were extended so each successful billable `/generate` action records:

- one API call
- its associated AI-token usage

The same idempotency key still maps to exactly one usage event, so a retry does not consume a second API call.

An automated boundary test verifies that API call 1000 is allowed on the Free plan and call 1001 is rejected with HTTP 429.

### Test database isolation

The first Stripe test module attempted to switch SQLite database files after SQLAlchemy had already created an engine.

This produced a SQLite readonly-database error because an existing engine still held connections to a deleted database file.

The test setup was corrected by explicitly disposing SQLAlchemy connections before deleting or recreating the test database.

A second isolation issue appeared when the reconciliation test depended on tables created by another test module.

That test was changed to create its own plans, tenant, subscription, and schema during setup.

### Migration-driven schema

Early application startup called `Base.metadata.create_all()`.

After Alembic migrations were established, this automatic table creation was removed.

The normal setup path is now:

1. `alembic upgrade head`
2. `python -m app.db.seed`
3. start the FastAPI application

A clean-room SQLite database was successfully created and used through only this documented path.

### Usage rollup indexing

Monthly usage queries filter by tenant and creation timestamp.

A composite index on:

`tenant_id, created_at`

was added through an Alembic migration to support this access pattern.

### Pricing profile

The pricing implementation was made explicit and auditable as the pinned `capstone-v1` profile.

Money uses integer micro-dollars:

`1 USD = 1,000,000 micro-units`

Cached input is cheaper than fresh input and reasoning tokens use the output-token rate.

### Repository secret hygiene

Before finalization, the repository was checked to confirm:

- `.env` is ignored
- `.env` is not tracked
- no Stripe secret pattern appears in current tracked files
- no Stripe secret pattern appears anywhere in Git history

The scans report only filenames on a match so secrets would not be printed accidentally.

## Final Automated Verification

The final automated suite at this stage reports:

`16 passed`

The only warning is a Starlette TestClient dependency deprecation warning and does not represent an application test failure.
