# Evals

200 tasks in `evalset/*.jsonl` (one file/category), per PLAN.md §3 / ASSUMPTIONS.md #13.

| category | count | grader(s) | category | count | grader(s) |
|---|---|---|---|---|---|
| arithmetic | 35 | numeric | multiple_choice | 20 | choice |
| classification | 30 | normalized | short_qa | 15 | normalized |
| dates | 25 | normalized/numeric/exact | units | 15 | numeric |
| extraction | 25 | exact/normalized/numeric | code | 10 | normalized/exact/numeric |
| strings | 20 | exact/numeric/normalized | summarization | 5 | contains_all |

Graders (`graders.py`, stdlib-only): `exact` strips whitespace; `normalized` casefolds + strips diacritics/punctuation/articles; `numeric` parses first number (commas/%/currency) within tolerance (`grader_args.tolerance` abs, else rel 1e-6); `contains_all` requires all `keywords` present (case-insensitive); `choice` extracts A-D from messy text.

Self-check: `python3 evals/graders.py` (validates schema + ids, identity-grades every task, prints per-category counts).
