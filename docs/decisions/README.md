# Decision records

These records capture design choices from the project brief. Accepted means agreed direction, not implementation or verification.

| Record | Status |
| --- | --- |
| [0001: Use PostgreSQL for durable staging](0001-postgresql-durable-staging.md) | Accepted; implementation pending |
| [0002: Isolate evaluation from matching](0002-isolate-evaluation.md) | Accepted; implementation pending |

## Open decisions

Resolve and record these before implementing the affected behavior. Include the chosen rule, rationale, and verification evidence when available.

| Area | Unresolved choice |
| --- | --- |
| Source identity | Provider ID scope and stability across files; handling conflicting reuse; evidence for grouping distinct duplicate entries. |
| Money and normalization | Accepted source formats, reference normalization, excess decimal precision, absent fees, and treatment of negative amounts, refunds, and reversals. |
| Timing | Source date formats, date-only cutoff and equality semantics, grace duration, and how source completeness is established. No banking calendar is assumed. |
| Matching | Candidate windows, minimum scores and margins, handling of competing claims and unequal amounts, and the development evidence that justifies those choices. |
| Recovery | PostgreSQL claim mechanism, lease and retry settings, publication locking, and how to verify a database and raw-storage restore together. |
| Evaluation | Duplicate-group counting, per-category units, and handling undefined precision/recall. No accuracy target or metric has been established. |
| Runtime and access | Tested dependency and container pins, access controls for raw evidence and evaluator truth, and the deployment/backup model. |
