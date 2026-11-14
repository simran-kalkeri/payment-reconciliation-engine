# 0003: Use reciprocal candidate confidence

**Status** Implemented and evaluated on a held-out synthetic seed.

Use exact reference and gross evidence first, then a unique exact-reference amount diagnostic, then fuzzy reference similarity within amount and date blocks. Require both endpoints to favor the link. Leave ties and uncertain links available for review.

Development compared score and margin pairs 80/6, 88/8, and 94/10. None produced a false link. They missed 12, 22 and 167 true links respectively. The demo selected 80/6 and wrote the frozen configuration before evaluating the held-out seed. See the [development selection](../../artifacts/evidence/development-selection.json) for measured results.
