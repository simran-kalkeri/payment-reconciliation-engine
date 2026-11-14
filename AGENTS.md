# Payment Reconciliation Engine

Install from `requirements.lock` and run `reconcile migrate`, `reconcile demo`, and `python -m pytest -q` from the root. Use the database and test environment settings in the [README](README.md#setup-run-and-test).

- Build a modular Python application with PostgreSQL-backed durable staging. Keep ingestion, transformation, matching, reporting, and evaluation separate.
- Parse money with `Decimal` and store integer minor units. Handle fees, currency, date formats, timezones, and settlement deadlines explicitly. Never use binary floating point for financial calculations.
- Keep answer keys, ground-truth pairings, and any generator labels or internals that reveal them out of the matcher's reach. Only the independent evaluator may use ground truth to score results.
- Preserve raw files and rows, including genuine duplicate settlements. Quarantine invalid rows with a reason code and a readable explanation; keep processing valid rows when row boundaries are reliable.
- Use transactions, stable identities, uniqueness constraints, and recoverable worker claims. Commit canonical writes and staging completion together. Make retries and reruns safe, including after a lost acknowledgement.
- Enforce deterministic one-to-one matching within each result version. Leave ambiguous candidates for review. Preserve reviewer resolutions and append-only application audit history across reruns.
- Require Alembic migrations for schema changes and tests for changed behavior. Use real PostgreSQL for transaction, concurrency, and recovery tests. Never commit secrets, fabricate metrics, or claim unexecuted tests passed.

See [architecture](docs/architecture.md) for boundaries and required checks, [business rules](docs/business-rules.md) for financial and matching policy, [decisions](docs/decisions/README.md) for open choices, and the [runbook](docs/runbook.md) for operational procedures.
