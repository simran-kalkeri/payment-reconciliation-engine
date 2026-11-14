# Reconciliation demo results

Development seed 4242 compared three fuzzy configurations. Each used exact and diagnostic matching first, with candidates limited by merchant, account, currency, and forward date window. Fuzzy candidates also had to agree in reconstructed gross. The engine compared normalized references and required a reciprocal top candidate with a minimum lead on both sides. Score/margin pairs of 80/6, 88/8, and 94/10 missed 12, 22, and 167 development links respectively, with zero false links in all three runs. The demo froze 80/6 before scoring seed 90125.

| Exception category | TP | FP | FN | Support | Precision | Recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Missing settlement | 140 | 0 | 12 | 152 | 100% | 92.11% |
| Duplicate settlement | 140 | 0 | 0 | 140 | 100% | 100% |
| Amount mismatch | 153 | 0 | 0 | 153 | 100% | 100% |
| Late settlement | 164 | 0 | 0 | 164 | 100% | 100% |
| Reference mismatch | 151 | 0 | 12 | 163 | 100% | 92.64% |

Across three business dates, the held-out run produced 12,248 correct links out of 12,260 available true links. Exact, diagnostic and fuzzy passes each produced zero false links. The matcher held all 24 deliberately ambiguous ledger entries for review. In each of the 12 two-ledger groups, one entry had a true settlement with a mistyped reference and the other had none. The same settlement scored equally for both. Abstention therefore missed one true link and withheld both the reference mismatch and missing classifications for that group. Eight invalid input rows were excluded from business scoring. [Metrics and case evidence](../artifacts/evidence/README.md)

Raw-file content hashes and source-scoped row identities distinguish redelivery from actual duplicate settlements. PostgreSQL holds each worker claim through canonical insertion and staging completion, so a crash rolls both back. An acknowledgement lost after commit leaves a completed row that another worker skips. The demo redelivered all four evaluation files and reprocessed 24,844 staged rows. Both business hashes and all durable counts matched. A reviewer resolution recorded in an early snapshot survived when a later settlement cleared the anomaly. A separate dump and restore verified the raw hashes, business snapshots and review counts. [Recovery and rerun evidence](../artifacts/evidence/README.md)

The next improvement would be to evaluate an independent provider-supplied payment identifier or timestamp as additional evidence for the tied references. Those 12 groups had the same merchant, amount, date eligibility and reference score. An independent signal could distinguish them while retaining reciprocal confidence. The measured results cover synthetic inputs and the documented source contract.
