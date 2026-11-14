# Business rules

## Input contract

Schema version 1 uses UTF-8 CSV with a header. Column order may vary. The file declaration supplies its kind, source and date format.

| Kind | Required columns |
| --- | --- |
| Ledger | `id`, `merchant`, `account`, `reference`, `currency`, `gross`, `collection_date`, `deadline_date` |
| Settlement | `id`, `merchant`, `account`, `reference`, `currency`, `net`, `fee`, `settlement_date`, `available_at` |

The source and row ID identify an entry within its kind. Identical normalized redelivery maps to the same canonical record. A source that reuses an ID with changed canonical values receives an `identity_conflict` quarantine record. Distinct settlement IDs survive even if their reference and amounts agree. This contract assumes IDs are stable across deliveries within each source.

Required fields are trimmed. References additionally use uppercase and remove whitespace. Merchant, account, and IDs remain case sensitive. Raw bytes and parsed field values are kept. An invalid header, malformed quoting or invalid UTF-8 rejects the file. Recoverable row shape errors and invalid values quarantine the row with a code and readable reason.

INR uses 100 paise per rupee. Amount fields require decimal text with at most two fractional digits. Missing fees and excess precision are quarantined. Gross must be positive, and net and fee must be nonnegative. Refunds, reversals and unsupported currencies are quarantined. The comparison uses settlement gross = net + declared fee. Stored and reported amounts are integers.

Date formats are `iso` (`YYYY-MM-DD`), `dmy` (`DD/MM/YYYY`) and `named` (`DD-MMM-YYYY` with an uppercase English month). Declare `mixed` when a file uses more than one of these formats. Slash-separated dates always use day/month/year. Business days use Asia/Kolkata. `available_at` and the run cutoff require seconds and a UTC offset. PostgreSQL stores instants as `timestamptz`. A deadline date is inclusive until the start of the next local day. Missing is eligible at that instant plus configured grace. A date-only settlement counts as late when its local day starts at or after that boundary. The default grace is zero. Weekends and holidays follow ordinary calendar days.

## Matching and exception lifecycle

1. A settlement is eligible when `available_at <= cutoff`. Within the declared file set, block candidates by merchant, account, currency and the configured forward calendar window from collection date.
2. Exact candidates must also share reference and gross. A unique candidate with a unique claimant links. For multiple candidates from one provider with a unique claimant, the uniquely earliest settlement day and arrival identify the observed original. Additional entries are duplicate evidence. Tied originals or competing claimants go to review.
3. A unique remaining exact-reference candidate with a different gross links in the diagnostic pass and produces an amount mismatch. Conflicting claims go to review.
4. Fuzzy candidates must have equal gross. Score normalized references with integer Damerau–Levenshtein similarity. The top score must meet the floor, and both endpoints must prefer each other by at least the configured margin over their respective runners-up. Keep candidates within the score retention floor for evidence. Fuzzy acceptance produces a reference mismatch. The matcher uses no global assignment optimization.

The engine tracks missing, duplicate, amount, late, reference, ambiguous, unexpected, and data-quality exceptions. A ledger with no link and no retained ambiguity stays pending until its deadline. Ambiguous ledger rows and their contested settlements are review evidence. An accepted link can still have multiple anomalies. A later result can clear or reactivate an anomaly while preserving reviewer state and history.

## Daily reports and independent scoring

Reports include input manifest hashes, source completeness attestation, run and configuration IDs, and conservation checks. Source row counts and warnings cover the full selected files. Financial populations use ledger collection day. Linked and duplicate settlements follow their owning ledger date; unowned settlements use settlement day. For cross-day consistency, use the same file set, rules, and cutoff for all dates in a reporting batch.

Outstanding collections, unexplained absolute discrepancies, duplicate exposure, late-settled value, and unresolved review exposure are separate INR paise measures. Categories can overlap and there is no aggregate loss figure.

Evaluation uses the ledger ID for missing, amount, late and reference metrics. For duplicates it uses the ledger ID, original settlement ID and exact set of extra settlement IDs as one group. Each multilabel case contributes independently to its applicable categories. Expected availability follows each report's cutoff and grace. Malformed rows are tracked separately, and an undefined precision or recall is JSON `null`.
