# Orchestrator log — CONTEXT2.md

File 2. First entry: E-0058. Previous file: `CONTEXT.md` (E-0001 … E-0057; closed at ~61 KB, past the ~50 KB threshold in CLAUDE.md).
Append-only. Mistakes are corrected by a new `CORRECTION` entry, never by editing.
Times are Asia/Colombo.

---

### E-0058 · 2026-11-13 20:37 (Asia/Colombo) · T01.2 · MERGED
Context: Owner: "Merged #7". Confirmed: PR #7 merged into master as `52fc2f9` (normal merge). T01.2 ticked.
Now available (no prompts until the owner asks, E-0057): T01.4, T01.6, T03.9, T03.4, T06.1. T01.3 after T01.4 merges.
Next in flight: the T02.1 handoff (PR not yet seen by the Orchestrator).
Also: started CONTEXT2.md because CONTEXT.md passed ~50 KB.

### E-0059 · 2026-11-13 21:05 (Asia/Colombo) · T02.1 · NOTE
Context: T02.1 round-1 handoff (Antigravity / Gemini, pasted by the owner). Checked against the PR: [Guna210/Skald#8](https://github.com/Guna210/Skald/pull/8), branch `task/T02.1-epub-fixtures` at `03cd551` (3 commits), based on `e3327d8` (PR #6 merge), not current master `52fc2f9`. 28 files, +1549: make_epubs.py 432, 11 TOML defs, 11 generated EPUBs (2.3–6.9 KB, ZIP_STORED), 2 Gutenberg EPUBs in `core/tests/data/public_domain/` (pg43 Jekyll & Hyde 304,737 B; pg46 Christmas Carol 148,017 B), SOURCES.md, test_epub_fixtures.py (7 tests). SPEC: T02.1 ticked; two Appendix 3 rows (TOML via tomllib; ZIP_STORED + fixed timestamps/order), as decided in E-0049. CI on the old base: PR run 43394031881 success. Independent reader: EPUBCheck 5.4.0 (cached in gitignored `.cache/`): 01–09 clean, 10 DRM reports encrypted resource (expected), 11 fatal RSC-016 (expected), pg46 clean, pg43 1 upstream aria-label error.
Problem: `git merge-tree` shows a conflict with master in SPEC.md (Appendix 3 rows appended at the same place as T01.2's rows).
Decision: Rebase-only prompt to the Builder first (still round 1; no review yet): rebase onto master, keep both sides of the Appendix 3 conflict (master's rows first, then the 2 T02.1 rows), force-with-lease push, report the new CI run and the full core test count (T01.2's tests + T02.1's). Then one Reviewer prompt on the rebased branch: fresh Claude Sonnet (Builder was Gemini). Same pattern as T01.1 (E-0040/E-0041).
Review focus to carry: every C1.1 rule really encoded in a def's [expected] block; no shared code with the parser; determinism test actually regenerates and compares bytes; Gutenberg redistribution terms (licence header kept intact) and SOURCES.md; the pg43 EPUBCheck error is upstream and acceptable as a real-world fixture; file sizes reasonable for the repo.
Follow-up: rebase handoff, then REVIEW-PROMPT.
