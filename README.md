# Payment Reconciliation Engine

Reconcile a collections ledger against bank or UPI settlements. The engine preserves raw inputs, stages and normalizes rows in PostgreSQL, matches eligible payments, and publishes daily reports with exception and review evidence.

## Setup, run, and test

From the repository root, with Python 3.14.4 and PostgreSQL 17.12:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
Copy-Item .env.example .env
```

On Linux or macOS, activate with `source .venv/bin/activate` and copy with `cp .env.example .env`. In `.env`, set a local `POSTGRES_PASSWORD` and set `RECON_DATABASE_URL` to `postgresql+psycopg://reconciliation:<URL-encoded-password>@127.0.0.1:55432/reconciliation`. Use a disposable database for the synthetic demo. Use the same URL or a separate test database for `RECON_TEST_DATABASE_URL`. The test role must be able to create schemas and a temporary database role.

```text
docker compose up -d --wait db
reconcile migrate
reconcile demo
python -m pytest -q
```

If PostgreSQL already runs locally, supply its URL and start with `reconcile migrate`. Set `RECON_REQUIRE_POSTGRES=1` for a test run that fails when the test URL is missing. The default demo uses the frozen configuration. Run `reconcile demo --retune` to repeat the development comparison, freeze its winner, then evaluate the held-out seed. Results are written under `artifacts/work/`.

The default host demo uses a trusted operator process. For a restricted matcher, provision a separate login named `recon_matcher` using `CREATE ROLE recon_matcher LOGIN` and psql's `\password recon_matcher`. Apply [matcher grants](scripts/matcher-grants.sql) as the schema owner. Set `RECON_MATCHER_URL` to that role's connection URL using host `db` and port `5432`, then run `reconcile demo --isolated --retune`. Compose mounts only the rules and export directories into the matcher container. The matcher image has no generator or evaluator code. Give that database role only the grants in the script.

The full host demo and real PostgreSQL suite ran on native PostgreSQL 17.12. The restricted matcher entry point and PostgreSQL grants were exercised separately. See the [verification evidence](artifacts/evidence/README.md) for environment and test results.

## Operator commands

| Task | Example |
| --- | --- |
| Generate CSVs and a separate answer key | `reconcile generate artifacts/work/inputs artifacts/work/truth --seed 4242` |
| Capture and stage a file | `reconcile ingest artifacts/work/inputs/ledger.csv ledger ledger-office` |
| Check file IDs and validation | `reconcile files` |
| Process staged rows | `reconcile worker --name local --file 1 --file 2` |
| Start a persistent worker or inspect readiness | `reconcile worker --watch`, `reconcile health` |
| Reconcile explicit file membership | `reconcile reconcile daily 2025-05-12 2025-05-18T00:00:00+05:30 --file 1 --file 2 --sources-complete` |
| Re-export a published snapshot | `reconcile report 1` |
| Score exported results offline | `reconcile evaluate artifacts/work/truth/answer_key.json --result artifacts/work/exports/run-1/result.json` |
| Verify already staged rows and a replay | `reconcile verify-rerun daily 2025-05-12 2025-05-18T00:00:00+05:30 --file 1 --file 2` |
| List and inspect reviews | `reconcile issues list --scope daily --status open`, `reconcile issues show 1` |
| Resolve or reopen | `reconcile issues resolve 1 --version 1 --actor operator --reason "Confirmed with bank"`, `reconcile issues reopen 1 --version 2 --actor operator --reason "Revised statement"` |
| Read audit history | `reconcile issues history 1` |

Replace example file, result, run, and exception IDs with those from your database. Ingest each file in the manifest and pass its declared `--date-format` when it differs from ISO. Include all applicable file IDs and attest source completeness only after verifying the batch. An incomplete run exports a diagnostic and exits with status 2.

## Project guide

- [Agent instructions](AGENTS.md) and [implementation plan](docs/implementation-plan.md)
- [Architecture](docs/architecture.md) and [design decisions](docs/decisions/README.md)
- [Input contracts and business rules](docs/business-rules.md)
- [Runbook, backup, and recovery](docs/runbook.md)
- [Measured results and one-page write-up](docs/write-up.md)
- [Synthetic datasets and verification artifacts](artifacts/evidence/README.md)
