# Payment Reconciliation Engine

The engine is intended to reconcile expected collections from a ledger with settlement entries from a bank or UPI provider, explain discrepancies, and preserve the evidence needed to review them.

**Status: documentation only.** At inspection, the repository contained only Git metadata. Application code, a dependency manifest and lockfile, Compose configuration, migrations, synthetic data, the CLI, and automated tests are not implemented. There are no measured accuracy, rerun, or recovery results.

## Setup, run, and test

Run these checks from the repository root. They were executed in the Windows workspace while preparing these docs. The tool versions observed here are not project pins or compatibility claims.

| Purpose | Verified command | Observed result |
| --- | --- | --- |
| Setup: check Python | `python --version` | Python 3.14.4 |
| Setup: check the Compose CLI | `docker compose version` | Docker Compose v2.38.2-desktop.1; Docker Engine readiness was not verified. |
| Run: check for Compose configuration | `docker compose config --quiet` | Failed: no configuration file. |
| Test: check the pytest runner | `python -m pytest --version` | pytest 9.0.3 |
| Test: check collection | `python -m pytest -p no:cacheprovider --collect-only -q` | No tests collected. This does not count as a passing test run. |

Project installation, database startup and migration, generation, ingestion, workers, reconciliation, reports, evaluation, the review workbench, and the end-to-end demo have no runnable commands yet. When those pieces land, replace the probes with instructions verified from a clean checkout, including the full demo and real PostgreSQL test commands.

## Repository guide

The current project files are the root `AGENTS.md`, this README, and the pages under `docs/`:

- [Agent and contributor rules](AGENTS.md)
- [Architecture and verification plan](docs/architecture.md)
- [Business rules and input contracts](docs/business-rules.md)
- [Decision records and unresolved choices](docs/decisions/README.md)
- [Operational runbook](docs/runbook.md)
