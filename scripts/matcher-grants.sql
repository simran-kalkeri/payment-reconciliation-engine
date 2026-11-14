-- Run as the schema owner after creating a LOGIN role named recon_matcher.
-- Adapt the schema or role names for deployment.
GRANT USAGE ON SCHEMA public TO recon_matcher;
GRANT SELECT ON input_files, canonical, canonical_membership, input_quality TO recon_matcher;
GRANT SELECT, INSERT, UPDATE ON operations, current_results, exceptions TO recon_matcher;
GRANT SELECT, INSERT ON matcher_configs, results, matches, exception_history TO recon_matcher;
GRANT USAGE ON SEQUENCE operations_id_seq, results_id_seq, exceptions_id_seq, exception_history_id_seq TO recon_matcher;
