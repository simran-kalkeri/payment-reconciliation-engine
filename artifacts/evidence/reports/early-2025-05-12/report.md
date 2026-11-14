# COMPLETE reconciliation for 2025-05-12

Monetary measures use INR paise. Exposure categories can overlap.

| Field | Value |
| --- | --- |
| scope | evaluation |
| business_date | 2025-05-12 |
| cutoff | 2025-05-13T18:30:00+00:00 |
| inputs | [{"date_format": "iso", "kind": "ledger", "schema_version": 1, "sha256": "64d87afc3be9e4c2e2712a44bbac36f43b2b893247274c7f62798230f4bab0d2", "source": "ledger-office"}, {"date_format": "named", "kind": "ledger", "schema_version": 1, "sha256": "959d70e9afe2d7e792361e425afaa5035ed1e1742680bef24ad4cb1a08f508b1", "source": "ledger-office"}, {"date_format": "dmy", "kind": "settlement", "schema_version": 1, "sha256": "17b3a35bab1cc02eef3178dc2e1455df85924bd0482c3e583f0e8391d365d769", "source": "upi-bank"}, {"date_format": "iso", "kind": "settlement", "schema_version": 1, "sha256": "18e3a4f1372107cf0a450d6fae0e3174c91ff0da17b0b424a36db4e65a6e06cb", "source": "upi-bank"}] |
| matcher_version | 1.0.0 |
| config_hash | 261d4372520fb9b529baf8a60fd65d5b6c60cea1831f7afa0cf69bceba599766 |
| grace_hours | 0 |
| source_completeness_attested | True |
| status | complete |
| context_hash | 00b0171d7193adb9b47f4cfaf01adca7cc7b10ab13ac03b434b69e7a12001383 |
| unit | INR paise |
| source_population | All declared file rows, across business dates |
| financial_population | Ledger collection day; owned settlements follow the ledger, unowned use settlement day |
| input_rows | 24844 |
| accepted_rows | 24836 |
| rejected_rows | 8 |
| pending_rows | 0 |
| ledger_count | 4139 |
| settlement_count | 4076 |
| ledger_matched | 4016 |
| ledger_unmatched | 123 |
| settlement_matched | 4016 |
| settlement_unmatched | 60 |
| exact_matches | 3919 |
| fuzzy_matches | 45 |
| diagnostic_matches | 52 |
| pending_not_due | 0 |
| pending_expected_gross | 0 |
| expected_gross | 1844747879 |
| expected_gross_matched | 1791622726 |
| expected_gross_unmatched | 53125153 |
| settlement_gross | 1815613053 |
| settlement_net | 1815435778 |
| settlement_fees | 177275 |
| settlement_gross_matched | 1791632809 |
| settlement_gross_unmatched | 23980244 |
| exception_counts.ambiguous_match | 10 |
| exception_counts.amount_mismatch | 52 |
| exception_counts.data_quality | 8 |
| exception_counts.duplicate_settlement | 50 |
| exception_counts.late_settlement | 0 |
| exception_counts.missing_settlement | 113 |
| exception_counts.reference_mismatch | 45 |
| exception_counts.unexpected_settlement | 10 |
| data_quality_warnings.invalid_amount | 2 |
| data_quality_warnings.invalid_date | 2 |
| data_quality_warnings.invalid_field | 2 |
| data_quality_warnings.unsupported_currency | 2 |
| exposure.duplicate_exposure | 23831244 |
| exposure.late_settled_value | 0 |
| exposure.outstanding_expected | 49399383 |
| exposure.unexplained_amount_discrepancy | 11683 |
| exposure.unresolved_review_exposure | 3725770 |
| conservation.expected_gross | True |
| conservation.input_rows | True |
| conservation.ledger_count | True |
| conservation.one_to_one | True |
| conservation.settlement_count | True |
| conservation.settlement_gross | True |
| run_id | 20 |
| result_id | 10 |
| result_hash | 56eb536e23e8272f64546f29605393b60b42c126bd7d9505b70d06097b10603d |
