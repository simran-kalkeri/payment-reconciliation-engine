# Verification evidence

The run used Python 3.14.4 and native PostgreSQL 17.12 on Windows. A fresh virtual environment installed from the lockfile, passed `pip check`, and exposed the `reconcile` CLI. The [test report](test-results.xml) records the unit and real PostgreSQL cases. The Compose configuration passed validation. The local Docker Linux engine did not become available, so the Compose container run was delegated to the repository's verification workflow.

| Deliverable | Evidence |
| --- | --- |
| Synthetic development data | [Manifest](datasets/development/manifest.json), [ledger](datasets/development/ledger.csv), [settlements](datasets/development/settlements.csv), and two alternate date-format inputs named in the manifest |
| Synthetic held-out evaluation data | [Manifest](datasets/evaluation/manifest.json), [ledger](datasets/evaluation/ledger.csv), [settlements](datasets/evaluation/settlements.csv), and two alternate date-format inputs named in the manifest |
| Answer keys | [Development](truth/development/answer_key.json) and [held-out evaluation](truth/evaluation/answer_key.json), stored outside input and matcher runtime paths |
| Threshold comparison | [Development results](development-selection.json) and [frozen configuration](../../config/frozen.json) |
| Daily reports | [Early May 12 snapshot](reports/early-2025-05-12/report.md), [May 12](reports/2025-05-12/report.md), [May 13](reports/2025-05-13/report.md), and [May 14](reports/2025-05-14/report.md). Each includes companion JSON and CSV files. |
| Evaluation | [Metrics](metrics.json) and [mistake analysis](mistake-analysis.json) |
| Rerun and reviewer evidence | [Counts and hashes](rerun.json) and [review history](review.json) |
| Backup/restore | [Source verification](restore-source.json) and [restored verification](restore-check.json) |
| Test and failure recovery evidence | [JUnit results](test-results.xml) |

The published inputs and answer keys are synthetic and intended for reproducibility. For an independent assessment of later matcher changes, generate a new held-out seed and keep its answer key private until configuration is frozen.
