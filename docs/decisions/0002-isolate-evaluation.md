# 0002: Isolate evaluation from matching

**Status** Implemented. The restricted entry point and database grants were exercised with real PostgreSQL.

Only the evaluator may use ground-truth pairings and seeded labels to score results. The generator creates the answer key separately from matcher inputs. The matcher consumes canonical records and versioned configuration; the evaluator consumes published result exports and the answer key. Freeze the matching configuration after development tuning and before evaluation on a separate seed.

The isolated image contains only allowlisted matcher modules and mounts rules and an export directory. The restricted PostgreSQL role reads canonical records and staging status views. Separate truth is available only to the generator and the offline evaluator. An integration test runs the restricted entry point with truth absent and verifies that the role cannot query an evaluation table or raw staged payloads.
