# Business rules

These are requirements and proposed input contracts for the initial engine. They are not implemented. Open policy choices are tracked in the [decision index](decisions/README.md).

## Inputs and money

| Input | Required information |
| --- | --- |
| Ledger | Stable ledger record ID, merchant/account scope, payment reference, currency, expected gross amount, collection date or timestamp, and expected settlement date or deadline. |
| Settlement | Stable settlement entry ID, provider identity, merchant/account scope, payment reference, currency, net amount, declared fee, settlement date or timestamp, and arrival date or timestamp. |

Retain original values alongside normalized values. Parse decimal amounts with `Decimal`, convert to the declared currency's integer minor units, and quarantine invalid amounts and unsupported currencies. The initial scope is INR (100 paise per rupee). For a fee deducted from a payment, compare ledger gross against `settlement net + declared fee`; report gross, net, and fees separately. Excess precision, missing fee, and refund/reversal policies must be decided explicitly before accepting affected rows.

Use Asia/Kolkata for business dates and UTC for stored instants. Treat date-only values as local calendar dates until a source rule gives them a time or cutoff. Accept only declared date formats; quarantine ambiguous or invalid dates. Banking-calendar support is out of scope for the initial design unless explicitly added and tested.

## Eligibility, matching, and exceptions

- A settlement must have arrived by the as-of cutoff to be eligible. A collection that is not yet due stays pending. Classify a missing settlement only when its configured deadline and grace period have passed and available evidence supports the classification. Record source incompleteness rather than implying a final result from partial inputs.
- Exact matching uses merchant/account scope, normalized reference, currency, reconstructed gross, and temporal eligibility. Keep repeated settlement entries as evidence; file replay or identical provider redelivery must not create a new business entry. Conflicting reuse of a provider ID needs review or quarantine under a declared source contract.
- Fuzzy matching considers only remaining eligible candidates within scope, currency, date, and amount bounds. Require both a minimum score and a margin over the runner-up; resolve competing claims consistently on both sides. Never use input order to break an ambiguous tie. Diagnose exact-reference amount differences separately so amount filtering cannot hide them.
- Track `missing_settlement`, `duplicate_settlement`, `amount_mismatch`, `late_settlement`, and `reference_mismatch`, plus `ambiguous_match`, `unexpected_settlement`, and data-quality issues. Multiple exceptions may apply to one transaction; a confirmed match may still have exceptions. A weak candidate alone is insufficient evidence for a reference mismatch.
- Retain rule/configuration version, scores, competing candidates, amount and date differences, and the reason for accepting or abstaining. Reviewer actions require an actor, a reason, a timestamp, and previous/new states. Reruns and late arrivals must preserve prior snapshots and human history.

## Reporting and evaluation

Label reports with business date, cutoff, run and configuration identifiers, input hashes, and completeness. Reconcile input, accepted, rejected, and pending counts and matched/unmatched counts per side. Report monetary totals per currency. Keep outstanding, discrepancies, duplicate exposure, late-settled value, and unresolved review exposure separate; do not add overlapping categories or equate exposure with loss.

Evaluate in isolation on a held-out seed after freezing matcher rules on development data. Define per-category counting units and as-of eligibility before measuring, including duplicate groups and overlapping labels. Report actual true positives, false positives, false negatives, precision, recall, support, incorrect and missed links, and abstentions. Separate invalid-input cases from business exceptions and define how undefined metrics are displayed.
