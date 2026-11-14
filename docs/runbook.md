# Operational runbook

Use the [setup instructions](../README.md#setup-run-and-test) and work from the repository root. The demo uses local files and a trusted operator. Keep access to raw and rejected payloads restricted to intake and authorized reviewers. A reviewer-supplied actor name is an audit label. Use managed database and filesystem credentials for deployment, with a separate schema owner, matcher and operator roles.

| Situation | Action |
| --- | --- |
| File rejected | Run `reconcile files`. Verify the source, manifest, hash, and error. Obtain a corrected file and ingest it as new input. Retain the rejected bytes. |
| Rows quarantined | Use `reconcile issues list --category data_quality` after publication, then `reconcile issues show ID`. Correct at the source. Keep quarantine evidence and distinguish data errors from business anomalies. |
| Worker exits or database becomes unavailable | Check the PostgreSQL server and `reconcile health`. Restart the worker with the same file IDs. An interrupted transaction releases claims; already committed rows remain processed. Re-submit the same bytes if file extraction stopped before completion. |
| Reconciliation incomplete | Verify declared file IDs and batch completeness, check file and row status, and finish ingestion or normalization. Use the same date and cutoff when replaying the intended context. |
| Reviewer conflict | Reload the exception and retry with its current version. Use a nonempty reason for resolve or reopen. Read the complete audit history with `reconcile issues history ID`. |
| Late arrival or revised rules | Reconcile the new input context. Read historical reports with `reconcile report RESULT_ID`. Compare the current exception and its history with prior snapshots. |

Run `reconcile health` to inspect database readiness, worker heartbeats, backlog age, rejection totals, operation duration and failures. Example alerts are an active worker heartbeat older than 30 seconds, a backlog with no progress for five minutes, rising failures, or rejection rates above the source's established baseline. A killed process may leave a stale operational record. Claims are independent PostgreSQL locks. Routine logs contain IDs, error codes, and stage outcomes. Protect database dumps, raw backups and result exports as financial evidence.

## Backup and restore drill

Quiesce writers so the database dump and raw-file copy describe the same point. Use PostgreSQL client tools with a service definition or password file and replace the example database names with your own. Set `RECON_DATABASE_URL` to the source first:

```text
python scripts/verify_restore.py artifacts/work/raw
pg_dump -Fc -d reconciliation -f recon.dump
```

Copy the raw directory into backup storage, keeping its hash-based hierarchy. Restore into a new database and a separate raw directory:

```text
createdb reconciliation_restore
pg_restore --exit-on-error --no-owner --no-privileges -d reconciliation_restore recon.dump
```

Set `RECON_DATABASE_URL` to the restored database and run `python scripts/verify_restore.py RESTORED_RAW_DIR`. Compare the source and restore summaries, including raw file hashes, staging counts, deterministic result hashes, and audit/review counts. Reapply deployment-specific grants before switching services. The verification script and actual drill are linked in the [evidence index](../artifacts/evidence/README.md).

Local raw-file retention and the database audit trigger are application safeguards. Deployment still needs managed backup retention, role provisioning, monitoring delivery, and a policy for object lock.
