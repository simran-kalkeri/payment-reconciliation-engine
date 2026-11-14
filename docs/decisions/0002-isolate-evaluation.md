# 0002: Isolate evaluation from matching

**Status:** Accepted design; implementation pending.

Only the evaluator may use ground-truth pairings and seeded labels to score results. The generator creates the answer key separately from matcher inputs. The matcher consumes canonical records and versioned configuration; the evaluator consumes published result exports and the answer key. Freeze the matching configuration after development tuning and before evaluation on a separate seed.

Enforce this boundary at runtime as well as in code. The matcher must lack access to truth files, tables, labels, and any generator internals that expose correct links. The exact storage and privilege layout is open. Verify that a matcher run succeeds with the truth inaccessible and that no matcher import depends on truth-bearing code.
