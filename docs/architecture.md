# Architecture

This is the intended architecture. There is no runtime implementation or test suite yet.

## Boundaries

Use one modular Python application. Typer exposes operator commands, SQLAlchemy and Psycopg connect to PostgreSQL, Alembic owns schema changes, and RapidFuzz scores reference similarity. Pin dependencies and container versions and verify them together before documenting setup.

| Planned location | Responsibility |
| --- | --- |
| `src/reconciliation/generator/` | Generate reproducible ledger and settlement CSVs, a manifest, and a separately held answer key. |
| `src/reconciliation/ingestion/`, `storage/` | Capture original files in content-addressed storage, register manifests, and extract rows into PostgreSQL staging. |
| `src/reconciliation/normalization/` | Validate staged rows, preserve source evidence, and write canonical ledger and settlement entries or quarantine rows. |
| `src/reconciliation/matching/`, `exceptions/` | Match eligible canonical rows, persist evidence and exceptions, and record state changes. |
| `src/reconciliation/reporting/`, `workbench/` | Publish versioned reports and support human review without rewriting source financial records. |
| `src/reconciliation/evaluation/` | Compare exported results to the isolated answer key; measure pair and exception accuracy. |
| `migrations/`, `config/`, `tests/`, `artifacts/` | Own schema history, versioned rules, unit and PostgreSQL integration/recovery tests, and demo outputs. |

These paths are planned. Only the root guidance and `docs/` exist today.

## Durable processing

1. Capture raw bytes before processing and register content hash, source, type, schema version, storage location, status, counts, and timestamps. Identify staged rows by file identity and row number; retain the raw payload, attempt/claim state, timestamps, and canonical or rejection reference.
2. Claim bounded batches transactionally. If processing outlives the claim transaction, use expiring leases and fence writes with a claim token. Commit canonical writes and staging completion together. Retry transient failures within a budget; quarantine permanent row errors and visibly fail malformed files or unexpected stage errors.
3. Enforce canonical identity and one-to-one matching with database constraints. Version results by business scope, cutoff, input set, configuration, and matcher version. Prevent conflicting publication within a scope and expose incomplete attempts separately from completed snapshots.
4. Keep matches, exceptions, and reviewer workflow distinct. Record automatic and human transitions in application append-only history. Hash deterministic business results separately from run IDs, timestamps, and other operational metadata.
5. Give the matcher canonical inputs and matching configuration only. Isolate answer keys, truth labels, and generator internals behind separate runtime access. The evaluator can read truth and result exports and cannot feed answers back to the matcher.

## Required automated checks

**Pending:** There is no application to exercise. Add these checks alongside the relevant code and migrations.

| Rule | Check to add |
| --- | --- |
| Ground truth stays isolated | Check matcher import boundaries and run it in an environment where truth files and stores are inaccessible. |
| Amounts and dates are explicit | Unit-test decimal conversion, currency and date validation, fee reconstruction, and deadline/cutoff boundaries. |
| Raw evidence and duplicates survive | Test valid rows beside a quarantined row, file rejection for invalid structure, identical redelivery, and two genuine settlement entries with the same reference and amount. |
| Claims and writes are recoverable | With real PostgreSQL, test interrupted ingestion, worker contention, expired claims and stale writes, rollback, commit with lost acknowledgement, temporary database unavailability, and reprocessing already staged rows. |
| Matching is one-to-one and safe to abstain | Test competing candidates and reversed input order; check merchant/currency and as-of boundaries. With real PostgreSQL, verify database constraints and concurrent publication. |
| Reruns preserve reviews and financial results | Verify stable business hashes and no duplicate matches, exceptions, or replay-generated history. Check that late arrivals preserve prior snapshots and reviewer decisions; incomplete runs cannot publish complete reports, and overlapping exceptions do not inflate exposure. |
