# Implementation plan

1. Pin the runtime, migrate the PostgreSQL schema, and implement raw capture, staging, normalization, and worker recovery.
2. Implement deterministic matching, versioned publication, exception review, and reporting.
3. Generate separate development and evaluation datasets. Select the matcher configuration from development outcomes before running the held-out evaluation.
4. Exercise retries, database contention, as-of changes, restore, and reviewer preservation. Publish evidence and push the verified changes.

The initial contract uses INR, Asia/Kolkata calendar dates, a date-only deadline at the start of the following local day, zero grace by default, and no banking calendar. Source-scoped identities identify canonical deliveries. Distinct settlement entry IDs survive deduplication. Configuration and declared file membership determine an immutable reconciliation context.
