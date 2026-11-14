# COMPLETE reconciliation for 2025-05-13

Monetary measures use INR paise. Exposure categories can overlap.

| Field | Value |
| --- | --- |
| scope | evaluation |
| business_date | 2025-05-13 |
| cutoff | 2025-05-17T18:30:00+00:00 |
| inputs | [{"date_format": "iso", "kind": "ledger", "schema_version": 1, "sha256": "64d87afc3be9e4c2e2712a44bbac36f43b2b893247274c7f62798230f4bab0d2", "source": "ledger-office"}, {"date_format": "named", "kind": "ledger", "schema_version": 1, "sha256": "959d70e9afe2d7e792361e425afaa5035ed1e1742680bef24ad4cb1a08f508b1", "source": "ledger-office"}, {"date_format": "dmy", "kind": "settlement", "schema_version": 1, "sha256": "17b3a35bab1cc02eef3178dc2e1455df85924bd0482c3e583f0e8391d365d769", "source": "upi-bank"}, {"date_format": "iso", "kind": "settlement", "schema_version": 1, "sha256": "18e3a4f1372107cf0a450d6fae0e3174c91ff0da17b0b424a36db4e65a6e06cb", "source": "upi-bank"}] |
| matcher_version | 1.0.0 |
| config_hash | 261d4372520fb9b529baf8a60fd65d5b6c60cea1831f7afa0cf69bceba599766 |
| grace_hours | 0 |
| source_completeness_attested | True |
| status | complete |
| context_hash | 25e75093be08ba168f2d6a45d5afb2209fcb5c76fe58005fa6f3fd6578da55c9 |
| unit | INR paise |
| source_population | All declared file rows, across business dates |
| financial_population | Ledger collection day; owned settlements follow the ledger, unowned use settlement day |
| input_rows | 24844 |
| accepted_rows | 24836 |
| rejected_rows | 8 |
| pending_rows | 0 |
| ledger_count | 4137 |
| settlement_count | 4151 |
| ledger_matched | 4093 |
| ledger_unmatched | 44 |
| settlement_matched | 4093 |
| settlement_unmatched | 58 |
| exact_matches | 3994 |
| fuzzy_matches | 41 |
| diagnostic_matches | 58 |
| pending_not_due | 0 |
| pending_expected_gross | 0 |
| expected_gross | 152251300 |
| expected_gross_matched | 151050700 |
| expected_gross_unmatched | 1200600 |
| settlement_gross | 154821871 |
| settlement_net | 154635491 |
| settlement_fees | 186380 |
| settlement_gross_matched | 151059286 |
| settlement_gross_unmatched | 3762585 |
| exception_counts.ambiguous_match | 8 |
| exception_counts.amount_mismatch | 58 |
| exception_counts.data_quality | 8 |
| exception_counts.duplicate_settlement | 47 |
| exception_counts.late_settlement | 51 |
| exception_counts.missing_settlement | 36 |
| exception_counts.reference_mismatch | 41 |
| exception_counts.unexpected_settlement | 6 |
| data_quality_warnings.invalid_amount | 2 |
| data_quality_warnings.invalid_date | 2 |
| data_quality_warnings.invalid_field | 2 |
| data_quality_warnings.unsupported_currency | 2 |
| exposure.duplicate_exposure | 1810300 |
| exposure.late_settled_value | 1589900 |
| exposure.outstanding_expected | 971400 |
| exposure.unexplained_amount_discrepancy | 11986 |
| exposure.unresolved_review_exposure | 229200 |
| conservation.expected_gross | True |
| conservation.input_rows | True |
| conservation.ledger_count | True |
| conservation.one_to_one | True |
| conservation.settlement_count | True |
| conservation.settlement_gross | True |
| run_id | 22 |
| result_id | 12 |
| result_hash | 85bec3191d2c8c75e5e3c9075f0944efae1bc783ab08aa66afa1d7ae1010cdc4 |
