# Payment Reconciliation Engine

[![PostgreSQL integration tests and isolated demo](https://github.com/simran-kalkeri/payment-reconciliation-engine/actions/workflows/verification.yml/badge.svg?branch=main)](https://github.com/simran-kalkeri/payment-reconciliation-engine/actions/workflows/verification.yml)
[![Python 3.14](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)](#tech-stack)
[![PostgreSQL 17](https://img.shields.io/badge/PostgreSQL-17-4169E1?logo=postgresql&logoColor=white)](#tech-stack)
[![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](compose.yaml)

I built this project to explore how payment reconciliation works when bank or UPI settlements arrive late, contain duplicates, or have inconsistent references. The engine compares expected collections with synthetic settlement data, sends uncertain matches to review, and makes it possible to replay the same files without duplicating records.

The local dashboard shows the pipeline from CSV generation through matching and evaluation. It also provides downloadable daily reports and a workbench for reviewing exceptions.

[Run locally](#setup-run-and-test) · [See the workflow](#reconciliation-workflow) · [View measured results](#evaluation-and-evidence) · [Tech stack](#tech-stack)

## Prerequisites

- Python **3.14** with `pip` and `venv`. The project was verified with Python **3.14.4**.
- **Docker Desktop** running with Docker Compose for the easiest PostgreSQL setup. The Compose file uses PostgreSQL **17.12**. An existing local PostgreSQL server and database can also be used.
- A web browser. The dashboard uses **8765** and the bundled PostgreSQL service uses **55432**. No Node.js setup is needed.

## Setup, run, and test

Open PowerShell in the project folder, where `README.md` and `compose.yaml` are located.

### First run on Windows

1. Create the Python environment and install the locked dependencies.

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.lock
   .\.venv\Scripts\python.exe -m pip install --no-deps -e .
   ```

2. Create `.env` if it does not exist and open it for editing.

   ```powershell
   if (-not (Test-Path .env)) { Copy-Item .env.example .env }
   notepad .env
   ```

   Choose a local password and set these two lines. Replace `YOUR_LOCAL_PASSWORD` in both places. URL encode the password in the database URL if it contains special characters.

   ```dotenv
   POSTGRES_PASSWORD=YOUR_LOCAL_PASSWORD
   RECON_DATABASE_URL=postgresql+psycopg://reconciliation:YOUR_LOCAL_PASSWORD@127.0.0.1:55432/reconciliation
   ```

3. Start PostgreSQL, initialize the schema, and open the dashboard. Use these same three commands for later starts. If you already have a local PostgreSQL server, point `RECON_DATABASE_URL` at a database you can use for the demo and start at the migration command.

   ```powershell
   docker compose up -d --wait db
   .\.venv\Scripts\reconcile.exe migrate
   .\.venv\Scripts\reconcile.exe dashboard --local-demo --open-browser
   ```

   Open [localhost:8765](http://localhost:8765/) if the browser does not open automatically. Keep the terminal running. Press **Ctrl+C** to stop the dashboard. If port 8765 is already in use, add `--port 8766` to the dashboard command. Local demo mode is for synthetic data and binds to this computer only.

If the portable Windows demo is already installed in `.local`, run `.\dashboard.cmd` instead. On macOS or Linux, create the environment with `python3.14 -m venv .venv`, use `.venv/bin/python` and `.venv/bin/reconcile`, and copy `.env.example` to `.env` with `cp`.

### Run a dashboard demo

1. Open **Pipeline** and click **Generate dataset**. Download the ledger CSV, settlements CSV, manifest, and answer key. The generated files cover two to seven recent business dates. Each new dataset varies the row count and the number of cases of each seeded error type.
2. Click **Run reconciliation** and follow the stages through **Evaluation**. Click a workflow node to see its rules and checks. The evaluation panel shows the measured table, false matches, and individual explanations for missed links.
3. Open **Daily reports** to see the dataset that just ran. Select a business date and download the report as CSV, JSON, or Markdown. The **Report version** picker distinguishes saved results for the same day. The settlement cutoff shows which arrivals were eligible, in IST.
4. Open **Exceptions**, choose an item, and click **Review**. Inspect the source evidence and resolve the case with your name and a reason. The audit history records the decision.
5. Return to **Pipeline** and click **Run again** to replay the same inputs. Compare the published result IDs and evaluation. To reproduce a saved dataset, use `.\.venv\Scripts\reconcile.exe generate artifacts/work/inputs artifacts/work/truth --from-manifest PATH_TO_MANIFEST`.

## Reconciliation workflow

```mermaid
flowchart LR
    G["Generate synthetic data"] --> C["Ledger and settlement CSVs"]
    C --> N["Stage and validate in PostgreSQL"]
    N --> M["Exact and fuzzy matching"]
    M --> R["Daily reports and exceptions"]
    R --> E["Score the results"]
    G --> K["Separate answer key"]
    K --> E
```

| Stage | What it does |
| --- | --- |
| **Generate** | Creates two CSVs with at least 10,000 valid rows and at most 15,000 data rows combined. Each dataset includes missing, duplicate, late, amount mismatch, and reference mismatch cases. Settlement rows include deducted fees, mixed date formats, and reference whitespace. |
| **Ingest and validate** | Verifies both file hashes, retains the original bytes, and stages rows in PostgreSQL. Workers parse money with `Decimal`, store integer paise, normalize dates and references, and quarantine invalid rows with reasons. |
| **Match** | Attempts exact reference and gross amount matches, then flags unique same-reference amount differences. The fuzzy pass compares references among equal-gross candidates in the date window. A pair must meet the score floor and lead competing candidates on both sides. |
| **Publish and review** | Publishes matched and unmatched totals and financial exposure by category. The exception workbench shows evidence and preserves each review decision, reason, and history. |
| **Evaluate** | Compares the published results with the answer key after matching. Shows precision and recall by error type, false matches by pass, and explanations of misses drawn from recorded candidate evidence. |
| **Replay** | Identifies repeat deliveries using file fingerprints and stable transaction IDs. An identical replay checks the result hash before reusing the report and preserves review history. |

## Evaluation and evidence

On the fixed-seed benchmark in this repository, the matcher linked **12,248 of 12,260 true pairs** with **zero false links**. Each missed link had tied candidates and went to review. The benchmark uses extra CSVs to exercise separate date-format declarations. A dashboard run uses one ledger CSV and one settlement CSV.

| Artifact | Where to find it |
| --- | --- |
| Matching rationale, precision and recall, and missed cases | [Write-up and metrics table](docs/write-up.md) · [Case evidence](artifacts/evidence/mistake-analysis.json) |
| Reproducible inputs and answer key | [Evidence index](artifacts/evidence/README.md) |
| Sample daily reconciliation report | [May 12 report](artifacts/evidence/reports/2025-05-12/report.md) |
| Rerun and review evidence | [Before and after record counts and result hashes](artifacts/evidence/rerun.json) · [Review history](artifacts/evidence/review.json) |

## Tech stack

| Layer | Technology |
| --- | --- |
| Engine | Python 3.14 and `Decimal` for exact money parsing |
| Data and migrations | PostgreSQL 17, SQLAlchemy, Psycopg, Alembic |
| Reference matching | RapidFuzz with Damerau–Levenshtein similarity |
| Dashboard and CLI | HTML, CSS, vanilla JavaScript, Python's HTTP server, and Typer |
| Local services and verification | Docker Compose, pytest, and GitHub Actions |

## CLI demo and PostgreSQL tests

After starting PostgreSQL and applying migrations, run the fixed-seed CLI demo to reproduce the benchmark:

```powershell
.\.venv\Scripts\reconcile.exe demo
```

The demo writes its reports, evaluation, and replay evidence under `artifacts/work/`. Use `--retune` to compare settings on the development seed before scoring the held-out seed. For the PostgreSQL test suite, add `RECON_TEST_DATABASE_URL` to `.env` with a local test database URL. Its role must be able to create schemas and temporary database roles. Then run:

```powershell
$env:RECON_REQUIRE_POSTGRES = "1"
.\.venv\Scripts\python.exe -m pytest -q
```

For a restricted matcher, provision the `recon_matcher` login, apply [matcher grants](scripts/matcher-grants.sql), and set `RECON_MATCHER_URL` to its connection URL using host `db` and port `5432`. Run `.\.venv\Scripts\reconcile.exe demo --isolated --retune` to use the Compose matcher. The matcher image has no generator or evaluator code and mounts only rules and exports. See the [verification evidence](artifacts/evidence/README.md).

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

On Windows, use `.\.venv\Scripts\reconcile.exe` in place of `reconcile` if the virtual environment is not active. Replace example file, result, run, and exception IDs with those from your database. Ingest each file in the manifest and pass its declared `--date-format` when it differs from ISO. Include all applicable file IDs and attest source completeness only after verifying the batch. An incomplete run exports a diagnostic and exits with status 2.

## Project guide

- [Agent instructions](AGENTS.md) and [implementation plan](docs/implementation-plan.md)
- [Architecture](docs/architecture.md) and [design decisions](docs/decisions/README.md)
- [Input contracts and business rules](docs/business-rules.md)
- [Runbook, backup, and recovery](docs/runbook.md)
- [Measured results and one-page write-up](docs/write-up.md)
- [Synthetic datasets and verification artifacts](artifacts/evidence/README.md)
