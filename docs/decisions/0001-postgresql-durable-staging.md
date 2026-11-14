# 0001: Use PostgreSQL for durable staging

**Status** Implemented and exercised on PostgreSQL 17.12.

Use PostgreSQL for the staging queue, canonical financial records, and application audit state. A worker can commit canonical writes and mark its staging row complete in one transaction. This avoids coordination with a separate broker for the initial workload. Use database uniqueness and recoverable claims to handle retries and contention.

Use transaction-scoped row locks with `SKIP LOCKED`. Claims never outlive their transaction, so there is no lease or fencing token to renew. Store raw bytes behind a content-addressed storage interface. The [runbook](../runbook.md) covers restoring both PostgreSQL and raw bytes.

Verify with real PostgreSQL under worker contention, abandoned claims, rollback, and lost acknowledgement after commit.
