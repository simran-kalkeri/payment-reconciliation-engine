# Operational runbook

**Status: planned.** There is no service, schema, or CLI to operate yet. The steps below define the intended recovery procedure; they have not been exercised. The [README](../README.md#setup-run-and-test) lists the only verified commands.

| Situation | Intended response |
| --- | --- |
| Input file fails validation | Retain the original bytes and rejection evidence. Check the source, schema version, hash, and diagnostic. Submit a corrected file as a new input; do not overwrite the original. |
| Individual rows are quarantined | Inspect rejection codes and counts while valid rows continue. Restrict access to raw payloads. Obtain a corrected source submission and retain the original rejection history. |
| Worker crashes or PostgreSQL is unavailable | Keep the run visibly incomplete. Restore database connectivity, inspect attempts, claims and backlog, and reclaim abandoned work through the supported worker path. A stale worker must be unable to commit. If commit status is uncertain, retry with the same identity. |
| Reconciliation needs a rerun | Use the same scope, cutoff, input hashes and rule versions for a replay. Compare canonical counts and business-result hashes; verify reviews and history survive. Publish a new result version for late arrivals or changed inputs or rules. |
| Candidate or exception needs review | Inspect source evidence, candidates and history. Record a reason when resolving or reopening; on an edit conflict, reload the current state. A local actor label is not authentication. |
| Database or raw storage is lost | Restore a consistent database backup and its corresponding raw files into an isolated environment. Verify manifests, raw hashes, row counts, pending claims, and audit history before resuming processing. A restore command and drill are still pending. |

Use structured logs keyed by run, file, row, stage, and error. Keep secrets and full sensitive payloads out of routine logs. Once monitoring exists, watch worker readiness, queue backlog and age, retries, rejection rates, run duration, and incomplete publication. Investigate stalled backlog, repeated failures, or unusual rejection spikes; alert thresholds and escalation ownership are open.

Local raw-file storage and application append-only history do not provide tamper-proof retention. Production access controls, backup procedures, and alerting need implementation and verification before deployment.
