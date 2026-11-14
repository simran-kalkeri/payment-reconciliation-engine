# 0001: Use PostgreSQL for durable staging

**Status:** Accepted design; implementation pending.

Use PostgreSQL for the staging queue, canonical financial records, and application audit state. A worker can commit canonical writes and mark its staging row complete in one transaction. This avoids coordination with a separate broker for the initial workload. Use database uniqueness and recoverable claims to handle retries and contention.

Store raw file bytes behind a storage interface. The initial design uses local content-addressed files; application write rules do not provide object lock. Database records and raw bytes must both be available for restore. The claim strategy, lease settings, and restore procedure remain open.

Verify with real PostgreSQL under worker contention, abandoned claims, rollback, and lost acknowledgement after commit.
