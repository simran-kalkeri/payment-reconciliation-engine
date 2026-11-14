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

## Local dashboard

For the portable Windows demo already installed in `.local`, run `.\dashboard.cmd` from the repository folder. It starts PostgreSQL if needed and opens [localhost:8765](http://localhost:8765/) without a sign-in link. Anyone with access to this computer can use this mode. Use it with sample data.

For other setups, start PostgreSQL, set `RECON_DATABASE_URL`, and run `reconcile dashboard --open-browser`. The default address is `http://127.0.0.1:8765/`. Use `--port` if that port is occupied. Leave the terminal running while you use the dashboard and press Ctrl+C to stop it.

Choose a scope, business date, and snapshot in **Daily reports**. Download reports as JSON, CSV, or Markdown. In **Exceptions**, filter the queue and select **Review** to inspect matching evidence, source rows, and audit history. Resolve or reopen a case by entering an operator name and reason. If the case has changed, reload it before submitting.

Click **Generate dataset** to create and download a ledger CSV, a settlement CSV and a manifest. The answer key is saved separately and is available as its own download for evaluation. Each click uses a fresh seed. Once the new files are ready, they replace the previous dashboard bundle in `artifacts/work/dashboard-datasets/`. Files you already downloaded stay on your computer. To reproduce a dashboard bundle, run `reconcile generate artifacts/work/inputs artifacts/work/truth --two-files --seed SEED`. Add `--merchant-profiles` when the manifest's configuration includes `"merchant_profiles": true`. Those bundles use merchant-specific payment amounts and fee rates, several settlement batches and uneven daily volumes. These are synthetic assumptions.

The dashboard opens on **Pipeline**. After generating a dataset, click **Run reconciliation**. The workflow canvas follows the run from reading both CSVs through evaluation. Click any stage to inspect its status and output, or select **Follow run** to resume following the active stage. The **Match** node shows exact, amount mismatch, and fuzzy passes. After all business dates are published, the independent evaluator reads the answer key and scores those results. The page shows precision and recall for the five seeded error types, false matches by pass, and explanations based on recorded candidate scores and matching rules. Open a date from the run or use **Daily reports** for full reports. Click **Run again** to replay the dataset. The latest completed evaluation for the current dataset survives a dashboard restart. Published reports and review history remain available in their dataset scope when you generate new inputs.

Run `reconcile migrate` before processing the mixed date layout. For CLI ingestion, use the manifest's source and date format with each file. The settlement CSV declares `--date-format mixed`. Score exported results separately using the answer key.

The server listens only on this computer. Outside local demo mode, the dashboard signs your browser in with a new private link each time it starts. If the browser does not open automatically, use the link printed in the running terminal. The operator name is recorded as an audit label.

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
