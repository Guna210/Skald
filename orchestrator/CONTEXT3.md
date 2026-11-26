# Orchestrator log — CONTEXT3.md

File 3. First entry: E-0118. Previous file: `CONTEXT2.md` (E-0058 … E-0117; closed at ~92 KB, past the ~50 KB threshold in CLAUDE.md). Older: `CONTEXT.md` (E-0001 … E-0057).
Append-only. Mistakes are corrected by a new `CORRECTION` entry, never by editing.
Times are Asia/Colombo.

---

### E-0118 · 2026-11-15 23:00 (Asia/Colombo) · — · NOTE
Context: Owner asked whether the context file is up to date for compaction. Orchestrator branch was fully pushed (0a753e4); CONTEXT2.md had reached ~92 KB / 60 entries.
Decision: Started CONTEXT3.md (this file). Rewrote STATE.md as a clean snapshot: removed finished deferred items (T01.2 R2-1/R2-2 done in T01.4; T02.1 R2-2 done in T02.2) and obsolete "decisions not yet in SPEC" (all now on master); grouped standing notes by the task they feed; fixed the garbled "recommended next step".
State at this point: master 3228b4a (PR #16). Merged PRs #2–#16 (T00.1–T00.4, T01.1–T01.6, T02.1, T02.2, T03.1, T03.4, T03.5). No open PRs. Available: T02.3, T03.2, T03.3, T03.7, T03.9, T06.1.
Follow-up: none.

### E-0119 · 2026-11-22 18:30 (Asia/Colombo) · T02.3, T03.2 · TASK-ASSIGNED
Context: Owner asked for the T02.3 and T03.2 prompts. Both from master 3228b4a, in parallel (separate code areas; both append Appendix 3 rows → the second PR to merge rebases).
Decisions in the prompts (Builders record them in Appendix 3):
T02.3 XHTML → paragraphs:
 - Reuse T02.2's resolve_body_slices/walk_body_slice and _collapse_ws unchanged (E-0099/E-0101/E-0103); expected paragraphs come from `[[expected.chapters]].paragraphs` in the TOML defs (independent of the parser).
 - Entry point `load_epub_book(path) -> Book` (what T02.7 calls). cover_path/source_path left None (T02.7 fills them when it writes the project).
 - Chapter.included = linear and not suggested_skip; title/linear/skip_reasons from T02.2.
 - Deterministic ids: chapter `ch_` + first 8 hex of sha256(f"{index}\0{full_href}"); paragraph `p_` + first 16 hex of sha256(chapter_id \0 paragraph index \0 text) — 64-bit to make collisions negligible (32-bit would be ~1% for a 10k-paragraph book). Amends B9's id rule for chapters too (deterministic output, golden-testable).
 - `<br>` → "\n" (strip each line, drop empty lines); table rows → cells joined by one space (fixture 05); h1–h6 → is_heading=True (provisional, E-0076); noteref elements (epub:type noteref, role doc-noteref) removed with their text, tails kept; note bodies (epub:type footnote/endnote, role doc-footnote/doc-endnote) skipped; img skipped (alt never read); script/style ignored.
 - NEW: page-break markers (epub:type="pagebreak", role="doc-pagebreak") skipped (page numbers must not be read aloud); `<rt>`/`<rp>` skipped (ruby annotations duplicate the base text). Both → docs/defaults.md + Appendix 3.
 - Acceptance sanity check: for chapters without notes, tables, <br> or page breaks, paragraphs joined by single spaces have the D2 length (± boundary spaces).
 - Carry T02.2 R3-1 (pin a dangling entry's position: nav a, gone, c, b) and T00.1 R1-1 (docs/defaults.md C1.1 item 5: alt text / note bodies skipped "by default").
T03.2 Catalog fetch, cache, compatibility:
 - NEW: core resolves <userData> via storage.py get_data_dir(): SKALD_DATA_DIR (T06.2 already passes it) → SKALD_DEV_DATA → Electron's default (Windows %APPDATA%\Skald, Linux $XDG_CONFIG_HOME/Skald, default ~/.config/Skald) — needed by the headless CLI (T05.8) too. catalog.cache.json lives there.
 - URL constant https://raw.githubusercontent.com/Guna210/Skald/master/catalog/catalog.json; override env SKALD_CATALOG_URL (dev/tests) + function parameter.
 - Remote catalog = untrusted input: 5 MiB cap via a new optional `max_bytes` on net.get_json (http_error over the cap); validate with the Pydantic `Catalog` schema only — NOT the CLI validator's repo checks (model cards, adapter registry, network), because the app must ignore unknown-adapter entries, not reject the catalog. Any parse/validation failure (incl. RecursionError) never crashes the core.
 - NEW ErrorKind `catalog_invalid` (B8 + ErrorKind): refresh job fails with it on an invalid remote catalog, job.log warning says why, cache untouched. schema_version newer than the app's → catalog_invalid with details reason "schema_too_new" and a hint to update Skald. Network errors keep net.py's kinds. Policy recorded: a catalog change an older app can't parse must bump schema_version (schema is extra="forbid").
 - Bundled fallback: no committed copy (would drift). One resource-root helper: dev = repo root (reuse validate.py's _REPO_ROOT), frozen = sys._MEIPASS; bundled catalog = <root>/catalog/catalog.json; adapter registry = <root>/worker/skald_worker/adapters/__init__.py via load_adapter_versions. T09.1 must ship both as data files.
 - catalog.get (sync): cache if valid, else bundled (warning logged if the cache is corrupt); result says `source: "cache"|"bundled"`. Annotations: revision compatible/reason with reason ∈ adapter_missing > adapter_too_old > app_too_old (app version skald_core.__version__ vs top-level min_app_version); checkpoint = its default revision's; model compatible = any checkpoint compatible. installed = `<storage>/models/<model>/<ckpt>/<rev>/.complete` exists (T03.6 writes it; T04.1 may refine for bundled revisions — provisional). update_available: checkpoint has an installed revision, its default revision is not installed and is compatible; model = any checkpoint; revision = installed and not the checkpoint's (compatible, uninstalled) default. fit = null stub (T03.3 fills).
 - Response models in skald_core/schemas, added to the schema export. Atomic write via the existing T01.5 helper. Two concurrent refreshes: atomic replace is enough, no lock.
 - Carry T03.1 R2-1: test that catalog.validate --network deletes each downloaded file after verification.
Reviewer plan: fresh Claude Opus for both (untrusted-input parsers), different model from each Builder.
Follow-up: owner opens two Builder sessions.

### E-0120 · 2026-11-22 19:10 (Asia/Colombo) · T02.3 · QUESTION + ANSWER
Context: T02.3 Builder Q1: fixture 02_epub2_ncx_only.toml body_xhtml line 31 has "…whenever the cold evening rain…", but expected.chapters[1].paragraphs[2] (line 71) omits "cold ". All other fixtures match 100%; every fixture without notes/tables/<br>/page breaks matches the D2 count exactly. Orchestrator confirmed both lines on master 3228b4a. Until now no test compared the expected paragraph text (test_epub_fixtures.py only asserts the list is non-empty), so the typo was never caught.
Decision: Option (a): add "cold " to line 71 only. Record it in Appendix 3 as a fixture-expectation correction approved by the Orchestrator.
Why: the expectation contradicts its own input, so this is a transcription typo, not a golden value edited to make a test pass. The input is right and its EPUB is committed. Its D2 counts were verified independently in the T02.1/T02.2 reviews, and changing the input would churn those bytes and counts for no gain. The Reviewer will check that the diff to the defs is exactly this one line.
Follow-up: tell the T02.3 Reviewer to confirm that no other expected value changed.

### E-0121 · 2026-11-22 19:40 (Asia/Colombo) · T02.3 · REVIEW-PROMPT
Context: T02.3 round-1 handoff (Antigravity / Gemini 2.5 Pro), PR #18 `task/T02.3-xhtml-paragraphs` @c44f4ce. Checked by the Orchestrator:
 - three commits on master 3228b4a, which is an ancestor;
 - 7 files, +724/−3: xhtml.py +287, test_xhtml_paragraphs.py +372, test_epub_structure.py +57 (R3-1), book/__init__ +2, SPEC.md (3 Appendix 3 rows + index tick), docs/defaults.md item 5, fixture 02 line 71;
 - epub.py UNCHANGED; the only fixture change is the approved line-71 "cold " fix (E-0120);
 - all 12 CI checks green at c44f4ce;
 - no secrets in the diff.
The Builder reports 243 passed. PR #17 (T03.2) is also open; its handoff has not been pasted yet.
Builder's own decisions:
 - `<br>` normalization also inside table cells; empty and &nbsp;-only cells are omitted before joining;
 - a final buffer flush, in xhtml.py's walker callbacks, so a slice that starts mid-`<p>` (an anchor inside a paragraph) still emits its text.
Builder's follow-ups on the public-domain EPUBs:
 - Gutenberg header, credits and licence chapters; untagged Contents and ILLUSTRATIONS tables;
 - Christmas Carol illustration captions (div.fig span) read mid-stave, duplicating the headings;
 - no class="pagenum" spans in either book.
Decision: Send to a fresh Claude Opus Reviewer (the Builder was Gemini; parser of untrusted input). FOCUS:
 - mid-paragraph anchor start and end: no duplicate or lost text across adjacent chapters;
 - skipped subtrees keep their tails (noteref, aside, img, pagebreak, rt);
 - mixed-content containers;
 - the id hash input is the final text;
 - the tests are meaningful (paragraph equality for every fixture, D2 sanity, noteref beside punctuation, id uniqueness);
 - nesting depth vs recursion;
 - Appendix 3 rows faithful to E-0119/E-0120.
Not findings (planned follow-ups): Gutenberg boilerplate and licence chapters are content for T02.8's text-review skim and T07.4's skip toggles. Figure captions (figcaption, Gutenberg div.fig) are not covered by C1.1 → decide at T02.8 whether to skip captions by default.
Follow-up: owner runs the Reviewer.

### E-0122 · 2026-11-22 20:30 (Asia/Colombo) · T02.3 · VERDICT
Context: Reviewer (fresh Claude Opus) round 1 on PR #18 @c44f4ce: APPROVED.
 - Checks: ruff and format clean; mypy clean (26 files); the targeted tests pass (60). The full suite was not run in the Reviewer's sandbox (psutil and pytest-timeout missing); CI is green (12/12, E-0121).
 - Confirmed: epub.py unchanged; the only fixture change is line 71 of fixture 02; the paragraph-equality test is parametrized over all 12 defs.
 - 10 mutations were all caught (noteref text kept, rt kept, cells without a space, flush removed, <br> joined by a space, index dropped from the id hash, heading_depth never cleared, suggested_skip ignored, both page-break checks).
 - Ad-hoc cases OK: an anchor mid-<p> or mid-inline gives no duplicated or lost text (Builder decision 2 is correct); an anchor on a noteref loses nothing; tails are kept; 200 nesting levels work; 3000 levels hit lxml's 256-level limit, recover to an empty chapter with a warning, and never crash.
Findings:
 - R1-1 [Minor] an anchor inside a heading (<h2><a id/>Title</h2>) → the title gets is_heading=False, because on_enter(h2) never fires; no text is lost; the shipped Gutenberg books are not affected.
 - R1-2 [Nit] <pre> collapses to one line.
 - R1-3 [Nit] a nested table's cells come out of order; stray text in a table.
 - R1-4 [Nit] a document deeper than 256 levels → empty chapter plus a warning.
Decision: Merge PR #18 (normal merge; mergeable, clean, head c44f4ce, CI green).
 - R1-1 → deferred to T02.8 (golden text tests): initialise heading_depth from start_el's h1–h6 ancestors, plus a test.
 - R1-2 → deferred to T02.8: decide whether <pre> keeps its line breaks like <br> (verse), and record it.
 - R1-3 dropped (rare).
 - R1-4 noted (no code change; useful if a user reports an "empty chapter").
Why: no blockers or majors; R1-1 affects only the heading flag (used later for pauses), so T02.8 is early enough.
After merge: T02.4 (TXT/MD import) and T02.5 (normalization + lexicon) become available (both depend only on T02.3). Owner rule E-0057: announce them, no prompts until asked. PR #17 (T03.2) will need a rebase on the new master before its review (both PRs append Appendix 3).
Follow-up: owner merges PR #18.

### E-0123 · 2026-11-23 09:30 (Asia/Colombo) · T02.3 · MERGED
Context: Owner: "Merged #18". master is now `2e178c5` = "Merge pull request #18 from Guna210/task/T02.3-xhtml-paragraphs" (normal merge).
Decision: T02.3 is done. T02.4 (TXT/MD import) and T02.5 (normalization + lexicon) are now available; announced only (E-0057).
Follow-up: none.

### E-0124 · 2026-11-23 09:35 (Asia/Colombo) · T03.2 · FIX-PROMPT (before review)
Context: T03.2 round-1 handoff (Antigravity / Gemini 3.1 Pro), PR #17 `task/T03.2-catalog-client` @9fcf034. It has three commits on 3228b4a. The Builder reports 239 passed locally on Linux.
Problems found by the Orchestrator:
 (1) CI is red: `core (windows-latest)` failed in both the push and the PR run; every other job is green. The failing test is test_catalog_client.py::test_first_offline_launch_serves_bundled_copy_when_refresh_fails: "Timed out waiting for job.finished" after 5 s.
     Cause: the test simulates "offline" with a real closed localhost port (_unused_local_port). On Windows each refused connect takes about 2 s (TCP SYN retries), so 3 attempts (2 retries) exceed the 5 s wait.
     The "1 lockfile(s) out of date" line in the log is the expected output of test_make_locks' drift test, not a failure.
 (2) Since #18 merged, PR #17 conflicts with master in SPEC.md (both PRs append Appendix 3 rows and tick the Part D index).
Decision: send it back to the Builder before review, with one prompt for both problems.
 - Rebase onto master 2e178c5. Keep both sets of Appendix 3 rows (T02.3's rows first, then T03.2's) and both index ticks. Push with --force-with-lease.
 - Fix the test so "offline" is mocked: patch the client's fetch or the net layer to raise SkaldError("offline"), or use a session that raises requests.ConnectionError immediately.
 - Do NOT raise the timeout, skip on Windows or mark the test flaky. Use no closed-port tricks in any test. The local fake HTTP server used by the other tests passed on Windows and may stay.
Why: SPEC C2 says tests mock the network; a real-socket timing test is OS-dependent and flaky. One combined round avoids an extra rebase pass.
Follow-up: once CI is green on both OSes, send the review to a fresh Claude Opus (the Builder was Gemini; untrusted remote input). FOCUS to include:
 - the Builder's three decisions: get_text plus parse in the client; empty RPC params so the fetch URL can't be redirected over RPC; the .complete path guard against unsafe id segments;
 - net.get_json's RecursionError mapping to http_error vs catalog_invalid in the client;
 - B8 and ErrorKind consistency.

### E-0125 · 2026-11-23 10:30 (Asia/Colombo) · T03.2 · REVIEW-PROMPT
Context: T03.2 pre-review fix handoff (Antigravity / Gemini 3.1 Pro), PR #17 @bdc3bea. Verified by the Orchestrator:
 - The PR is rebased on master 2e178c5 (master is an ancestor) and is mergeable and clean.
 - range-diff: commits 1–2 identical (=); commit 3 differs only in SPEC context (the T02.3 rows now sit above the T03.2 rows); the new commit 4 holds the O-1 test fix.
 - 12 files, +1687/−55: client.py +411, net.py ±152, methods.py, schemas (+84 models, +16 exports), storage.py +26, five test files (no lines removed from test_net.py), SPEC.md (+4 Appendix 3 rows, B8 catalog_invalid, index tick).
 - CI: all 12 checks green at bdc3bea (push run 45128982364 and PR run 45128988017; core windows-latest now passes).
 - No secrets in the diff.
 - O-1 fixed (requests.Session.request mocked to raise ConnectionError; closed-port helper removed); O-2 fixed.
Note: net.py was refactored, not just extended. _get_response_with_retries became _request_with_retries(read_body, max_bytes); _decode_text became _decode_bytes; a new _read_bounded_body reads the body inside the retry loop. The T01.6 behaviour must be preserved.
Decision: Send to a fresh Claude Opus Reviewer (Builder Gemini; untrusted remote input; touches defaults/paths). FOCUS:
 1. Behaviour of the net.py refactor vs the T01.6 Appendix 3 rules: retry rules (2 retries, never on 4xx), error kinds, download/resume/Range untouched, and whether a mid-body read error is now retried (acceptable if bounded and tested).
 2. The max_bytes cap is enforced while streaming (Content-Length is not trusted).
 3. catalog_invalid vs http_error: the client parses the JSON itself, so a malformed or deeply nested remote catalog must reach catalog_invalid; no core crash.
 4. The cache is never overwritten on any failure, and the write is atomic.
 5. Bundled fallback and a corrupt cache.
 6. Annotation rules and the update_available matrix exactly as in E-0119 and Appendix 3; ids unique only per parent.
 7. get_data_dir order and its OS defaults.
 8. The Builder's decisions: empty RPC params, so the fetch URL can't be redirected over RPC (agree); the .complete path guard against unsafe id segments.
 9. Schema export includes the new models.
 10. The tests are meaningful (mutation-check a few).
 11. Appendix 3 and B8 match E-0119.
Follow-up: owner runs the Reviewer.

### E-0126 · 2026-11-23 12:00 (Asia/Colombo) · T03.2 · VERDICT + FIX-PROMPT
Context: Reviewer (fresh Claude Opus) round 1 on PR #17 @bdc3bea: CHANGES REQUESTED.
 - Checks: ruff, format and mypy clean; 260 passed; the validator reports the catalog valid.
 - Hostile payloads (100k-deep list and object, NaN, [], null, a bare string, an empty string, schema_version 2 / 99.0 / "9" / a 5000-digit integer, an extra key, a BOM): all give catalog_invalid; nothing escapes.
 - Mutations caught: reason precedence, cache write, max_bytes in refresh, bundled source label, the update_available "default compatible" rule.
 - Mutations survived: the streaming cap disabled; the backslash clause of the safe-segment guard.
 - Confirmed: the cache is untouched on every failure; the write is atomic; both-unusable → a clean catalog_invalid; no RPC path to the URL override; get_data_dir is correct and tested; the schema export is complete; Appendix 3 and B8 match E-0119; the net.py refactor preserves the T01.6 rules.
Findings:
 - R1-1 [Major] the only no-Content-Length cap test sends non-JSON through get_json, so it passes on "Invalid JSON", not on the cap; disabling the streaming check leaves all tests green.
 - R1-2 [Minor] the safe-segment guard is tested only with "../outside" (the \, \x00 and empty clauses are untested).
 - R1-3 [Minor] a mid-body drop is now retried for get_text/get_json (bounded by MAX_RETRIES; accepted), but untested.
 - R1-4 [Nit] _decode_bytes uses UTF-8 errors="replace" when no charset is declared (the old path used chardet); a BOM-prefixed catalog → catalog_invalid.
Decision: Round 2, test-only plus one comment.
 - Fix R1-1: a valid-JSON over-cap body without Content-Length through get_text; a Content-Length under the cap with a real body over it; assert details max_bytes/actual_bytes or the "exceeds max_bytes" message.
 - Fix R1-2: a parametrized test of _is_safe_id_segment ("", ".", "..", "a/b", "a\\b", "a\x00b", a normal id) plus one case through annotate_catalog.
 - Fix R1-3: a mid-body drop through get_text succeeds on retry; exhausted retries → the mapped kind.
 - R1-4: a code comment plus an Appendix 3 row (UTF-8 with replacement when no charset; a BOM-prefixed catalog is rejected as catalog_invalid; raw.githubusercontent sends charset=utf-8). No behaviour change.
Why: the cap is the main defence against a hostile or huge catalog and must be proven by a test that fails without it. The rest is cheap and in the same files.
Follow-up: the same Reviewer session for round 2.

### E-0127 · 2026-11-23 14:10 (Asia/Colombo) · T03.2 · REVIEW-PROMPT (round 2)
Context: T03.2 round-2 handoff (Gemini 3.1 Pro), PR #17 @1aa9275. Verified by the Orchestrator:
 - one new commit on bdc3bea (no force-push); master 2e178c5 unchanged; mergeable and clean;
 - 4 files, +127/−9: test_net.py +107, test_catalog_client.py ±27, SPEC.md +1 Appendix 3 row, net.py +1 comment line only (no production behaviour change);
 - CI green 12/12 at 1aa9275 (push run 45140380840, PR run 45140391224).
The Builder reports 269 passed and says both new cap tests fail with the streaming check disabled.
Builder decision: the "Content-Length under the cap, real body over it" case uses gzip (compressed length < max_bytes < decompressed length). This is the realistic case: a server can't send more than its Content-Length over HTTP/1.1, but a gzip bomb can expand.
Decision: round 2 goes to the same Opus Reviewer session. FOCUS:
 - re-run the two mutations that survived (cap disabled, backslash clause removed), plus the \x00 and empty-segment clauses;
 - with gzip, does the read stop early, keeping memory bounded by the cap rather than by the decompressed size?
 - the R1-3 tests (retry recovers; exhaustion → offline after 3 attempts);
 - the R1-4 comment and Appendix 3 row;
 - nothing else changed.
Follow-up: owner pastes into the round-1 Reviewer session.

### E-0128 · 2026-11-25 12:45 (Asia/Colombo) · T03.2 · VERDICT
Context: Reviewer (same Opus session) round 2 on PR #17 @1aa9275: APPROVED.
 - Checks: ruff, format and mypy clean; 269 passed; the diff is tests plus one comment plus one Appendix 3 row.
 - All mutations are now caught: the cap disabled (survived in round 1), the cap loosened ×100, and the backslash (survived in round 1), \x00, empty-segment and "."/".." clauses.
 - Gzip bomb (300 MB of zeros → 1.37 MB, with Content-Length, max_bytes 5 MiB) → http_error with actual_bytes 5,308,416 (the cap plus one chunk) and about 0 MB RSS growth, so memory is bounded by the cap.
 - The R1-3 tests use a real truncated chunked body; exhaustion → offline, matching T01.6.
 - R1-1…R1-4 fixed.
 - New: R2-1 [Nit] the unbounded resp.content branch is not covered by the mid-body retry tests (no caller in this task).
Decision: Merge PR #17 (normal merge; mergeable and clean, head 1aa9275, CI green 12/12, E-0127). R2-1 is dropped and noted: add a test if a caller of the unbounded branch appears.
After merge: T03.6 (model file installer, revisions, licence acceptance; it needs T03.2 + T01.6 + T01.3) becomes available. Announce only (E-0057).
Follow-up: owner merges PR #17.

### E-0129 · 2026-11-25 12:48 (Asia/Colombo) · T03.2 · MERGED
Context: Owner: "Merged #17". master is now 327927d = "Merge pull request #17 from Guna210/task/T03.2-catalog-client" (normal merge). The owner asked whether the 5 MB cap also stops real EPUBs.
Decision: Answered no. The 5 MiB cap (MAX_CATALOG_BYTES) is used only by catalog/client.py when it fetches catalog.json; net.py's max_bytes is optional and off by default; model downloads use download() with the catalog's pinned size and SHA-256. EPUBs are local files with no download cap; T02.2 refuses only books over 500 MB uncompressed (MAX_UNCOMPRESSED_BYTES), and a typical novel EPUB is 0.3–5 MB.
T03.2 is done. T03.6 is now available (announced only, E-0057). Available: T02.4, T02.5, T03.3, T03.6, T03.7, T03.9, T06.1.
Follow-up: none.

### E-0130 · 2026-11-25 12:51 (Asia/Colombo) · T02.4, T02.5 · TASK-ASSIGNED
Context: Owner asked for the T02.4 and T02.5 prompts. Both build on master 327927d, run in parallel (separate files) and append Appendix 3 rows; the second to merge rebases.
Decisions in the prompts (the Builders record them in Appendix 3 and docs/defaults.md):
T02.4 TXT/MD import (book/text_import.py):
 - Return `TextImport(book, encoding, guessed)` (a dataclass), so T02.7 can job.log the guess. No dispatcher (book.import, T02.7, picks by suffix).
 - Encoding:
   - a BOM (UTF-8, UTF-16 LE/BE) is used and not a guess;
   - else strict UTF-8 success is not a guess;
   - else guessed: NUL bytes mostly at odd/even positions → UTF-16 LE/BE, then cp1252 if it decodes, else latin-1.
   - No new dependency for this (no chardet/charset-normalizer). Line endings → \n.
 - Limits: files over 100 MB → unsupported_format (hint: too large); no non-whitespace text → unsupported_format.
 - TXT paragraphs = blank-line-separated blocks. Single newlines inside a block are hard wraps → one space (Gutenberg). Whitespace collapsed.
 - Chapter rules:
   - (a) a block whose first line matches ^(chapter|part|book)\b (case-insensitive, after stripping) and is ≤ 80 chars;
   - (b) a single-line block ≤ 80 chars preceded by ≥ 2 blank lines.
   - The heading block's lines are joined by a space into the first paragraph (is_heading=True). Title = the heading's first line.
   - Text before the first heading is its own chapter. Untitled chapters → "Chapter N". No heading at all → one chapter.
 - Book.title = the file stem; authors []; language None (set later in T02.7).
 - Chapters: linear True; suggested skip "short" (< 200 chars, D2 counting); included = not suggested_skip.
 - Ids: reuse T02.3's _chapter_id/_paragraph_id with href key f"L{start_line}" (1-based start line).
 - Markdown: NEW dependency markdown-it-py (MIT; mdurl MIT), pinned exactly; tables enabled.
   - h1/h2 (ATX or setext) start chapters; h3–h6 are heading paragraphs.
   - Paragraph, list-item, blockquote and table-row blocks → paragraphs (cells joined by one space).
   - Inline: text and code_inline kept; softbreak → space; hardbreak → "\n".
   - Skipped: images (alt text never read), html_block/html_inline tokens (the text between inline tags is kept), and fenced/indented code blocks (not narration — a default, so it goes in defaults.md).
   - Why the dependency: CommonMark edge cases (emphasis, links, setext, lists) are error-prone by regex.
 - Fixtures: generated in tests via tmp_path (bytes for the encodings), with expected chapters in the test tables.
 - Reviewer: Opus (parser of untrusted input).
T02.5 normalization + lexicon (text/normalize.py, text/lexicon.py; pure functions):
 - normalize:
   - NFC;
   - remove U+00AD soft hyphen and U+200B, U+2060, U+FEFF;
   - KEEP U+200C/U+200D (ZWNJ/ZWJ are meaningful in Indic and Persian scripts and in emoji sequences; Kokoro supports hi);
   - every Unicode whitespace run without "\n" → one ASCII space; a run containing "\n" → one "\n"; strip the ends;
   - quotes and dashes untouched.
 - Synthesis text = apply_lexicon(normalize(display)); the display text (Paragraph.text) is never changed. The cache key and T02.6 chunking use the synthesis text.
 - Lexicon matching:
   - rule words are normalized the same way; one compiled alternation, longest word first, ties broken by rule order (earlier wins);
   - per-alternative case flag ((?i:…) unless case_sensitive); re.escape every word;
   - whole-word boundaries = (?<!\w) and (?!\w), not \b, so "C++" and "Dr." work and the boundaries are Unicode-aware;
   - a single left-to-right pass: leftmost match, longest at that position; replaced text is never rescanned (no cascades);
   - the replacement is inserted as written (no case transfer);
   - whole-word never matches inside CJK runs (\w includes CJK) → CJK rules need whole_word=false; document it and note it for T07.7.
 - apply_lexicon returns (text, per-rule counts) plus a helper to total counts over a Book.
 - LexiconRule.word gets min_length=1 after stripping (whitespace-only rejected).
 - Reviewer: Sonnet (Builder must not be Sonnet).
Follow-up: owner opens two Builder sessions.

### E-0131 · 2026-11-25 13:49 (Asia/Colombo) · T02.4 · REVIEW-PROMPT
Context: T02.4 round-1 handoff (Antigravity / Gemini), PR #19 `task/T02.4-text-import` @69fdf1e. Verified by the Orchestrator:
 - 2 commits on master 327927d (an ancestor); mergeable and clean; CI green 12/12; no secrets;
 - 7 files, +938/−1: text_import.py +360, test_text_import.py +558, book/__init__ +4, test_imports +2, pyproject (+markdown-it-py==4.3.0), docs/defaults.md +8, SPEC.md (4 Appendix 3 rows plus the index tick);
 - epub.py and xhtml.py unchanged (their helpers are imported).
The Builder reports 289 passed; the Windows wheel was checked with pip download. PR #20 (T02.5) is also open; its handoff has not been pasted yet.
Builder decisions, all accepted by the Orchestrator:
 (1) The BOM-less UTF-16 NUL-cadence check runs BEFORE strict UTF-8, because ASCII-range UTF-16 is valid UTF-8 with embedded NULs.
 (2) Markdown h1/h2 also emit a leading heading paragraph (matching TXT and EPUB).
 (3) A pre-heading Markdown chapter is created only once real content appears (no empty "Chapter 1" from a leading image or comment).
Decision: Send to a fresh Claude Opus Reviewer (the Builder was Gemini; parser of untrusted input). FOCUS:
 - decision 1's threshold: a valid UTF-8 file with a few stray NULs must not be misread as UTF-16, and the guessed flag must be correct in every case;
 - both chapter rules and their negatives;
 - the Markdown token handling (nested lists and quotes, tables, html_inline keeping its text, code skipped);
 - pathological inputs: linear time, no RecursionError;
 - D2 "short" counting; ids via the T02.3 helpers with L{start_line}; no empty paragraphs;
 - the dependency pin and licence;
 - Appendix 3 and defaults.md match E-0130;
 - tests are meaningful (mutations).
Follow-up: owner runs the Reviewer.

### E-0132 · 2026-11-25 13:58 (Asia/Colombo) · T02.4 · VERDICT + FIX-PROMPT
Context: Reviewer (fresh Claude Opus) round 1 on PR #19 @69fdf1e: CHANGES REQUESTED.
 - Checks: 289 passed; ruff clean; mypy stub errors local to the venv only; deps MIT and pinned exactly.
 - About 60 crafted inputs; 30 mutations, 25 caught.
 - Pathological inputs are linear with no RecursionError (4 MB single line 0.04 s; 1M blank lines 0.05 s; 400k paragraphs TXT 2.7 s, MD 9.5 s; 5000-deep lists 2 s).
Findings:
 - R1-1 [Major] the BOM-less UTF-16 heuristic misfires both ways, silently:
     (a) ASCII/UTF-8 with a few stray NULs (64 bytes/4 NULs, 160/10, 1600/100) → UTF-16 garbage;
     (b) BOM-less CJK UTF-16 with no NULs and all bytes < 0x80 → UTF-8 with C0 controls and guessed=False.
     The mutants threshold=1 and the dominance change survive.
 - R1-2 [Minor] an image-only, code-only or over-nesting-limit Markdown file → a Book with 0 chapters and no error.
 - R1-3 [Minor] inline <br> is dropped with no separator ("worldnext").
 - R1-4 [Minor, Orchestrator call] rule (a) checks only the first line, which in wrapped prose is always ≤ 80 chars, so "Part of the…" / "Book lovers…" paragraphs become chapters.
 - R1-5 [Minor] missing tests: NUL threshold; a heading inside a blockquote (tok.level == 0); the size boundary.
 - R1-6 [Nits] footnote "^1"; a UTF-32-LE BOM read as UTF-16; odd-length UTF-16; an assert in production code; a second "C1.1 Import" heading in defaults.md.
Decision: round 2.
 - R1-1 → replace the heuristic with an Orchestrator-specified algorithm based on which C0 control bytes appear in the raw bytes:
     1. BOM: UTF-32 BOMs are checked before UTF-16; decode with it; not a guess.
     2. The raw bytes have no C0 controls except \t\n\r\f → 8-bit path: strict UTF-8 → not a guess; else cp1252 → latin-1, guessed.
     3. Only NULs among the C0 controls → NUL cadence (even length; at least 30% of one parity's positions are NUL and at most 5% of the other's) → UTF-16 LE/BE, strict, guessed; else the 8-bit path with NULs stripped, guessed.
     4. Other C0 controls present → the cadence test; else strict utf-16-le, then -be, accepted only if the decoded text has no C0 controls except whitespace (LE first: Notepad's "Unicode"; a BOM-less BE CJK file may be misread as LE — accepted and documented); else the 8-bit path with C0 controls stripped, guessed.
   guessed=False only for a BOM or for clean UTF-8 (no C0 controls). Tests: every case above, the Reviewer's crafted inputs (a)/(b), and Cyrillic and CJK UTF-16 LE.
 - R1-2 → zero chapters → unsupported_format in both loaders, with tests.
 - R1-3 → an html_inline <br>, <br/> or <br /> (case-insensitive) → hardbreak "\n" (consistent with EPUB); every other html_inline stays skipped; with a test.
 - R1-4 → tighten rule (a): additionally the heading block has at most 3 lines and its first line has at most 8 words (wrapped prose lines are about 10–12 words; Gutenberg headings like "CHAPTER I." / "BOOK THE FIRST" or "BOOK ONE\nRECALLED TO LIFE" still match). Record this in Appendix 3 and defaults.md, with tests both ways.
 - R1-5 → tests: a heading inside a blockquote doesn't start a chapter; the size limit at its boundary (patched constant: exactly at the limit OK, limit+1 → error); plus the R1-1 tests.
 - R1-6 → fix the UTF-32 BOM (part of R1-1 step 1) and replace the production assert with explicit handling. Drop the footnote "^1" (out of scope), odd-length UTF-16 and the defaults.md heading.
Why: silent mis-decoding is user-visible garbage; the C0-control signature separates real UTF-16 (CJK: about 12% of chars give a low byte below 0x20) from 8-bit text with stray NULs, which a NUL-count threshold alone cannot. R1-4 is a real Gutenberg risk, cheap to tighten.
Follow-up: the same Reviewer session for round 2.

### E-0133 · 2026-11-25 14:07 (Asia/Colombo) · T02.4 · REVIEW-PROMPT (round 2)
Context: T02.4 round-2 handoff (Gemini), PR #19 @8a54fe2. Verified by the Orchestrator:
 - one new commit on 69fdf1e (no force-push); master 327927d unchanged and an ancestor; mergeable and clean;
 - 4 files, +280/−100: text_import.py ±180, tests ±184, SPEC.md, defaults.md;
 - CI green 12/12 (PR run 45577455442, push run 45577444043).
The Builder reports 299 passed (30 under -O) and that local mutations made the stray-NUL tests (old heuristic) and the R1-4 tests (limits removed) fail.
Builder decision: also reject a book whose chapters all have no paragraphs (e.g. "# ![](pic.png)") → accepted.
One shortcut comment: "LE tried before BE, BOM-less BE CJK may decode as LE" → the documented known limit (E-0132); a decision, not a finding.
Decision: round 2 goes to the same Opus Reviewer session. FOCUS:
 - the algorithm matches E-0132 step by step (C0 definition, the cadence thresholds and which parity maps to LE/BE, strict decoding, the guessed flag on every branch);
 - re-run the round-1 crafted inputs and surviving mutants;
 - the R1-2/R1-3/R1-4/R1-5 tests; no regressions in the round-1 confirmations;
 - the Appendix 3 rows were replaced, not duplicated.
Follow-up: owner pastes into the round-1 Reviewer session. PR #20 (T02.5) is still open; its handoff has not been pasted yet.

### E-0134 · 2026-11-25 14:11 (Asia/Colombo) · T02.4 · VERDICT + FIX-PROMPT (round 3)
Context: Reviewer (same Opus session) round 2 on PR #19 @8a54fe2: CHANGES REQUESTED.
 - Checks: 299 passed (30 under -O); no regressions; timings unchanged (100k chapters 2.5 s; 300k paragraphs 6.9 s).
 - R1-2/R1-3/R1-4 fixed; R1-1 partly fixed: stray NULs, LE CJK/Cyrillic, ASCII LE/BE and UTF-32 BOMs are now right.
 - Appendix 3 rows were replaced in place (4 rows, no duplicates).
Findings:
 - R2-1 [Major] step 4: a single stray C0 byte in an even-length 8-bit file (e.g. a trailing DOS Ctrl-Z \x1a; b"caf\xe9 \x1a end") → strict UTF-16-LE garbage, because arbitrary even-length bytes are almost always valid UTF-16 and pass the no-C0 check by accident.
 - R2-2 [Minor] BOM-less UTF-16 whose NUL cadence is broken by a few code units with a NUL low byte (emoji low surrogate DE00, U+0100, U+3000) → other parity over 5% → cp1252 garbage; correct in round 1.
 - R2-3 [Minor] surviving mutants: the cadence thresholds; the even-length check; guessed=True on three branches; strict vs errors="replace"; skipping the decoded-text C0 check; the C0 set (\f/\t); the <br regex (no <brx> test); the heading limits (8→7, 3→2/4); first-line word counting at the 8-word boundary.
 - R2-4 [Nit] "# ![](p.png)" followed by a real chapter keeps an empty "Chapter 1" (auto-skipped as short); a 2-line heading block with a 40-word line (intended).
Decision: round 3, narrowly scoped. This is the last round before CLAUDE.md's rethink rule (a third CHANGES REQUESTED would trigger it).
 - R2-1 FIX: in step 4, try the strict UTF-16 decodes only when the C0 bytes are at least 5% of the code units (C0 count ≥ 0.05 × len/2). Real BOM-less UTF-16 has about 11% (CJK low bytes) up to about 100% (Cyrillic high byte 0x04). Otherwise go straight to the 8-bit path with the C0 bytes removed, guessed=True. Tests: a trailing \x1a on even and odd lengths, in UTF-8 English, UTF-8 with accents and cp1252 with accents → correct text with \x1a removed, guessed=True.
 - R2-2 FIX (cheap, restores the round-1 behaviour): in steps 3 and 4, if one parity is at least 30% NUL but the other is over 5%, still try strict UTF-16 for the dominant parity's endianness before falling back. Test: "a 😀 "×40 BOM-less utf-16-le → correct text.
 - R2-3 FIX: one assertion per surviving mutant, including a boundary pair for 30%/5% and assertions on the guessed flag for every branch.
 - R2-4: no change. Note for T02.7: chapters with zero paragraphs can exist (dangling EPUB anchors, an image-only Markdown h1); the UI must handle them.
 - Update the Appendix 3 encoding row in place.
Why: R2-1 is a silent-garbage bug for ordinary DOS-era TXT files; the 5% fraction guard separates real UTF-16 from stray bytes. R2-2 and R2-3 are a few lines each and close the remaining gaps.
Follow-up: the same Reviewer for round 3.

### E-0135 · 2026-11-25 14:22 (Asia/Colombo) · T02.4 · FIX-PROMPT (round 3, pre-review)
Context: T02.4 round-3 handoff (Gemini), PR #19 @31955d4. Verified by the Orchestrator:
 - one commit on 8a54fe2; 3 files (text_import.py ±41, tests +194, SPEC row in place); CI green 12/12 (runs 45579521916 and 45579515459); mergeable.
The Builder reports 308 passed and 20 mutants killed.
Orchestrator smoke test of _decode_text_bytes (extracted with stubs, 13 cases): correct for clean UTF-8 (\t/\f kept, not a guess), a trailing \x1a on even and odd lengths in a 1.7 KB English file, cp1252 odd length, stray NULs, BOM-less UTF-16 LE/BE ASCII, LE CJK, Cyrillic, emoji and mixed, and a UTF-8 BOM.
FAILS: the Reviewer's own R2-1 example b"caf\xe9 \x1a end" (12 bytes) → utf-16-le garbage '慣ᨠ攠摮'. One C0 byte passes the 5% gate because the file has only 6 code units (1×20 ≥ 6). The Builder's tests used longer inputs.
Decision: pre-review fix O-1 (an Orchestrator finding, so it is not a Reviewer round):
 - the step-4 gate also needs an absolute minimum of 8 C0 bytes (MIN_UTF16_C0_BYTES = 8);
 - add the exact 12-byte case and its odd-length variant as tests, plus a boundary pair at 7 and 8 C0 bytes;
 - update the Appendix 3 row in place.
Real BOM-less UTF-16 books have hundreds of C0 code units; inputs that small aren't books.
Why: sending it to review as-is would very likely give a third CHANGES REQUESTED (the CLAUDE.md rethink rule) for a one-line fix.
Follow-up: after the fix, the round-3 review goes to the same Opus session.

### E-0136 · 2026-11-25 14:41 (Asia/Colombo) · T02.4 · REVIEW-PROMPT (round 3)
Context: T02.4 O-1 handoff (Gemini), PR #19 @c8230f4. Verified by the Orchestrator:
 - one commit on 31955d4 (no force-push); master 327927d; mergeable and clean;
 - 3 files, +53/−9: MIN_UTF16_C0_BYTES = 8 plus the gate, tests, the SPEC row in place;
 - CI green 12/12 (runs 45581050520 and 45581039834).
The Builder reports 309 passed and the 3 O-1 mutants killed. The Builder also adjusted the existing cjk_high_bytes and c0_at_5 tests so they meet the 8-byte floor → accepted.
Orchestrator re-ran its 13-case smoke test: all correct now, including b"caf\xe9 \x1a end" → cp1252 "café  end" guessed=True.
Known drift: docs/defaults.md "C1.1 Import (TXT and Markdown)" item 1 still describes the round-2 heuristic (no 5%/8-byte gate; old "≤ 5%" cadence). Appendix 3 is correct and is the record of truth.
Decision: defaults.md sync DEFERRED to T02.7 (the next task touching import; it copies the Appendix 3 encoding row's wording). The Reviewer is told this is not a finding.
Round 3 goes to the same Opus session, covering R2-1…R2-3 plus O-1.
Follow-up: owner pastes into the Reviewer session.

### E-0137 · 2026-11-25 15:17 (Asia/Colombo) · T02.4 · VERDICT
Context: Reviewer (same Opus session) round 3 on PR #19 @c8230f4: APPROVED.
 - Checks: 309 passed; the scope is the 3 files; the Appendix 3 row was replaced in place and matches the code.
 - R2-1 and R2-2 fixed (trailing \x1a even/odd; b"caf\xe9 \x1a end"; emoji, U+0100 and U+3000 UTF-16 LE/BE).
 - No stray-NUL regression; book-scale BOM-less CJK, Cyrillic and mixed text decode correctly as LE.
 - 26 of 30 mutants caught.
Findings:
 - R3-1 [Minor] surviving mutants: the BE-side 30% boundary, and \x0b/\x0c in _C0_CHAR_RE (plus 2 equivalent even-length mutants).
 - R3-2 [Nit] a tiny BOM-less no-NUL UTF-16 file (< about 8 C0 code units, e.g. 13 CJK chars) → 8-bit garbage, guessed=True; irrelevant for books.
 - R3-3 [Nit] BOM-less BE CJK/Cyrillic → LE garbage, guessed=True (the accepted known limit).
Decision: Merge PR #19 (normal merge; mergeable and clean, head c8230f4, CI green 12/12, E-0136).
 - R3-1 → deferred to T02.7 (add a BE 29%/30% pair and a decoded-text \x0b/\f case while there).
 - R3-2 and R3-3 → accepted limits; guessed=True lets T02.7 warn in the job log.
After merge: T02.6 is NOT unlocked yet (it needs T02.5). PR #20 (T02.5) will need a rebase on the new master before review (both PRs append Appendix 3 and tick the index).
Lesson for future prompts: when a fix cites a Reviewer's exact failing input, tell the Builder to test with that exact input. This avoided a third round here (O-1, E-0135).
Follow-up: owner merges PR #19.

### E-0138 · 2026-11-26 11:01 (Asia/Colombo) · T02.4 · MERGED
Context: Owner: "Merged #19". master is now 651f8a9 = "Merge pull request #19 from Guna210/task/T02.4-text-import" (normal merge).
Decision: T02.4 is done. Nothing new unlocks (T02.6 needs T02.5; T02.7 needs T02.4 + T02.6 + T01.3 + T01.5).
Follow-up: none.

### E-0139 · 2026-11-26 11:01 (Asia/Colombo) · T02.5 · FIX-PROMPT (rebase before review)
Context: T02.5 round-1 handoff (Gemini / Antigravity), PR #20 `task/T02.5-normalize-lexicon` @31b03db. Verified by the Orchestrator:
 - 2 commits on 327927d; 7 files, +587/−5: text/lexicon.py +172, normalize.py +24, text/__init__ +10, schemas/models.py ±11, tests +367, defaults.md ±4, SPEC.md ±4;
 - CI green 12/12 at 31b03db; no secrets;
 - after #19 merged it CONFLICTS with master 651f8a9 in SPEC.md (Appendix 3 and the index tick); docs/defaults.md auto-merges.
The Builder reports 322 passed.
Builder decisions:
 (1) the special characters are removed before NFC (idempotence) → accepted;
 (2) a single alternation WITHOUT capturing groups; the winning rule is resolved via exact_map/ci_map buckets keyed on (len, casefold) with an re.fullmatch fallback; patterns cached with lru_cache(32). The Builder measured 500 capturing groups as about 26× slower;
 (3) count_lexicon_matches(book, rules).
Orchestrator read lexicon.py. Risks for the Reviewer:
 - the bucket lookup can miss when re's IGNORECASE matches but casefold changes the length (e.g. U+0130 İ → "i̇"): then "return matched  # pragma: no cover" silently gives neither a replacement nor a count;
 - with two rules on the same word but different whole_word or case flags, the resolution order must match the regex alternation's priority;
 - the added complexity vs Ponytail is justified only if the benchmark holds.
Decision:
 - Rebase-only prompt first: onto 651f8a9; keep the T02.4 rows (already on master) then the T02.5 rows; keep both index ticks; check the auto-merged docs/defaults.md keeps both the T02.4 TXT/MD section and the T02.5 C1.2 edits; --force-with-lease; CI green.
 - Then a fresh Claude Opus Reviewer, upgraded from Sonnet (E-0130), because of the custom resolution logic in decision 2.
Follow-up: owner pastes the rebase prompt into the T02.5 Builder session.

### E-0140 · 2026-11-26 11:48 (Asia/Colombo) · T02.5 · REVIEW-PROMPT
Context: T02.5 rebase handoff (Gemini / Antigravity), PR #20 @40b78f7. Verified by the Orchestrator:
 - rebased on 651f8a9 (an ancestor); mergeable and clean;
 - range-diff: the code commit is identical (=); the docs/SPEC commit differs only in merge context;
 - the diff vs master has exactly the 2 T02.5 Appendix 3 rows plus C1.2 items 1–2, and the T02.4 section is untouched;
 - CI green 12/12 (runs 45762799046 and 45762792872).
The Builder reports 362 passed (this now includes T02.4's tests).
Orchestrator smoke test of apply_lexicon on the branch:
 - "İstanbul and istanbul" with rule "istanbul" → only the lowercase one is replaced. re's simple case folding never matches İ, so the regex and the buckets agree and nothing is silently missed.
 - STRASSE vs straße: not matched (simple folding).
 - "New York, York" → NY, Y.
 - A case-sensitive "smith" (rule 0) plus a case-insensitive "Smith" (rule 1) on "Smith smith" → B, A (the tie goes to the earlier rule).
 - "cat category" with a whole-word "cat" (rule 0) and a substring "cat" (rule 1) → C, Degory.
 - Greek final sigma, the ǅ/ǆ titlecase digraph and the long s ſ → matched, with counts correct.
 So the E-0139 silent-miss risk was not reproduced; the Reviewer still probes it.
Decision: send to a fresh Claude Opus Reviewer (E-0139). FOCUS:
 - the bucket resolution of decision 2 vs the alternation's priority (try to hit "return matched  # pragma: no cover");
 - the leftmost-longest rule and no cascades;
 - whether the benchmark claim justifies the complexity (Ponytail), or whether a simpler correct design exists at acceptable speed;
 - the lru_cache key and any mutation hazards;
 - normalize's order and idempotence; the whitespace rules; ZWNJ/ZWJ kept;
 - the LexiconRule constraint and the schema export;
 - tests are meaningful;
 - Appendix 3 and defaults.md match E-0130.
Follow-up: owner runs the Reviewer.

### E-0141 · 2026-11-26 12:45 (Asia/Colombo) · T02.5 · CORRECTION
Context: E-0140 says "re's simple case folding never matches İ, so the regex and the buckets agree and nothing is silently missed".
Decision: that is wrong. re.fullmatch("(?i:i)", "İ") is True (re-checked by the Orchestrator). The İstanbul result in E-0140 came from the reachable "return matched" no-op branch (the bucket lookup misses because casefold("İ") is 2 chars), exactly the risk E-0139 named. See the T02.5 R1-1 finding in E-0142.
Follow-up: none.

### E-0142 · 2026-11-26 12:45 (Asia/Colombo) · T02.5 · VERDICT
Context: Reviewer (fresh Claude Opus) round 1 on PR #20 @40b78f7: APPROVED.
 - Checks: the T02.5 and schema tests pass (59); ruff clean. The full suite and mypy were not reproducible in the Reviewer's sandbox (pytest-timeout and stubs missing); CI is green and is relied on.
 - Differential fuzz, 20k cases vs a capturing-group reference: 319 mismatches, all involving İ; 0 without İ (outputs and original-position counts).
 - Mutations caught: tie order, \b, rescan, removal order, ZWNJ/ZWJ removal. Not caught: dropping the casefold fallback.
 - normalize OK: idempotent; NBSP, U+202F, \t, \v, \f and \r → space; \r\n → \n; U+2028/2029 → space; ZWNJ/ZWJ kept.
 - Benchmark (500 ci whole-word rules × 10k paragraphs): Builder's design about 9 s, one capturing group per alternative 38.6 s (4.3× slower, so the claim holds), a bare dict lookup 3.7 s but correct only for uniform flags → complexity accepted.
 - lru_cache key and immutability OK.
Findings:
 - R1-1 [Minor] İ (U+0130): re's IGNORECASE matches i/İ, but the bucket key casefold("İ") = "i̇" (2 chars) misses → no replacement, no count; it can also pick a different same-length rule (rules "i" and "İ" on "İ" → rule 2 instead of rule 1).
 - R1-2 [Minor] the casefold fullmatch fallback is untested.
 - R1-3 [Nit] defaults.md should mention U+2028/2029 → space and \r\n → \n.
Decision: Merge PR #20 (normal merge; mergeable and clean, head 40b78f7, CI green 12/12). R1-1, R1-2 and R1-3 are CARRIED into T02.6 (same skald_core.text package, unlocked by this merge):
 - R1-1: make _ci_key consistent with re for İ (map casefold "i̇" → "i", alongside the existing ı → i), remove "# pragma: no cover", and add tests: rule "istanbul" on "İstanbul" is replaced and counted; rules "i" and "İ" on "İ" → rule 1 wins.
 - R1-2: a test where lower() differs but casefold is equal (rule "σίσυφος" vs "ΣΊΣΥΦΟΣ"), failing without the fallback.
 - R1-3: the defaults.md line.
Why: no blockers or majors; Turkish İ is a real but narrow case; carrying it saves a round trip, and T02.6 works in the same package.
After merge: T02.6 (sentence splitting, chunking, dialogue) becomes available (announce only, E-0057).
Follow-up: owner merges PR #20.

### E-0143 · 2026-11-26 12:48 (Asia/Colombo) · T02.5 · MERGED
Context: Owner: "Merged #20". master is now 96125f8 = "Merge pull request #20 from Guna210/task/T02.5-normalize-lexicon" (normal merge).
Decision: T02.5 is done. T02.6 is now available.
Follow-up: none.

### E-0144 · 2026-11-26 12:48 (Asia/Colombo) · T02.6, T03.3 · TASK-ASSIGNED
Context: Owner asked for the T02.6 and T03.3 prompts. Both from master 96125f8, in parallel (text/ vs hardware/; both append Appendix 3 rows and tick the index → the second to merge rebases).
Decisions (the Builders record them in Appendix 3 and docs/defaults.md):
T02.6 sentences, chunks, dialogue (text/chunk.py; pure functions):
 - Input = the SYNTHESIS text (E-0130). Main entry chunk_paragraph(chapter_id, paragraph_id, text, language, max_chars) → sentences, chunks, unbalanced_quotes. Storage is decided in T02.7/T05.4 (sentences don't depend on max_chars; chunks do).
 - Order: dialogue spans first, then sentence splitting WITHIN each span, then greedy packing within a span up to max_chars. Chunks never cross a span or a paragraph; Paragraph.sentences = the per-span sentences concatenated.
 - Ids: Sentence "s_" and Chunk "c_" + 16 hex of sha256(paragraph_id\0index\0text); Chunk.index is per paragraph; voice_id and cache_key are None (T05).
 - Language: the primary subtag of Book.language, lowercased; None → "en". pysbd if it supports the language (a cached Segmenter per language, clean=False); otherwise a punctuation fallback: [.!?…。！？؟।] plus trailing closing quotes/brackets, then whitespace or end (CJK terminators need no whitespace). If pysbd's segments don't reproduce the span (whitespace-normalized), use the fallback for that span and log a warning. "\n" is a sentence boundary.
 - Long sentence > max_chars: split at ; then : then , (plus the CJK ；：，、) then spaces, choosing the rightmost split ≤ max_chars and recursing; last resort a hard split at max_chars, never before a combining mark.
 - Reconstruction rule: " ".join(chunk texts) == the span or paragraph text with every whitespace run collapsed to one space.
 - Dialogue:
   - Quote pairs: “…”, "…" (straight quotes alternate), «…», 「…」 in all languages; „…“ for de, cs, sk, pl, bg, ro, hu (where “ closes), otherwise “ opens.
   - The span includes its quote marks.
   - At least 2 words (whitespace tokens), or at least 2 characters when the content has no whitespace (CJK).
 - NEW (approved change to the C1.2 step 6 default): an opener left unclosed at the end of a paragraph, with every earlier quote balanced, is the "continued speech" convention → dialogue to the paragraph end, NOT flagged. Any other imbalance → the whole paragraph is narrator and flagged (Paragraph.unbalanced_quotes).
 - Known limit: British single-quote ‘…’ dialogue is not detected (apostrophe conflict; not in the C1.2 list) → narrator voice.
 - Carry T02.5 R1-1/R1-2/R1-3 (E-0142).
 - Tests: recorded expectations for fixture passages; no chunk over max_chars; a reconstruction property loop (no new dependency); quotes in several languages; unbalanced cases; the pysbd SyntaxWarning scoped ignore (E-0048).
 - Reviewer: Opus (defaults, complex text logic).
T03.3 hardware probe + fit (hardware/probe.py, hardware/fit.py):
 - system.hardware is sync, registered in methods.py, and returns HardwareInfo (T01.4).
 - CPU model: Linux /proc/cpuinfo "model name"; Windows winreg HKLM\HARDWARE\DESCRIPTION\System\CentralProcessor\0 ProcessorNameString; fallback platform.processor().
 - RAM via psutil; disk free on the <storage> drive (the nearest existing ancestor of get_storage_dir()).
 - nvidia-smi:
   - lookup: shutil.which, then %SystemRoot%\System32\nvidia-smi.exe, then %ProgramFiles%\NVIDIA Corporation\NVSMI\nvidia-smi.exe;
   - run: 10 s timeout, stdout=PIPE, stderr captured, CREATE_NO_WINDOW on Windows;
   - parse: `--format=csv,noheader,nounits` (nounits approved as a deviation from B7), read with the csv module;
   - if compute_cap is rejected (old driver), retry without it → compute_cap None (GpuInfo.compute_cap becomes str | None), bfloat16 False;
   - missing, failing, timeout or garbage → [] plus a log warning, never an error;
   - the GPU list is cached for the process lifetime; RAM and disk are fresh on every call.
 - Fit (computed per MODEL hardware block — the schema puts hardware on the model, not the checkpoint; it is copied to each checkpoint; adapter tasks may extend the schema):
   - CUDA tier when the model has cuda, a GPU has memory_total ≥ min_vram_gb×1024 MiB, its driver ≥ the pack floor (packs.manager CUDA_DRIVER_REQUIREMENTS["cu126"][os]) and its compute_cap ≥ 5.0 (otherwise Not supported, reason gpu_too_old), and total RAM ≥ min_ram_gb if set.
   - Pick the eligible GPU with the most VRAM and record gpu_index.
   - Else the CPU tier if the model has cpu and total RAM ≥ min_ram_gb.
   - Else Not supported, with a reason code: needs_nvidia_gpu, not_enough_vram, not_enough_ram, driver_too_old, gpu_too_old, plus details (needed/have).
   - Rating:
     - great = ≥ 1.5× the tier's minimum (VRAM for cuda, RAM for cpu) AND a known rtf ≤ 0.5;
     - slow = a known rtf > 1 (either tier);
     - otherwise good (an unknown rtf caps at good).
   - Warnings (cap at good):
     - driver_below_recommended: floor ≤ driver < the 12.6 toolkit driver (E-0114);
     - gpu_generation_unconfirmed: compute_cap < 7.0 or unknown (do not promise Pascal).
 - Estimate: estimate_seconds = char_count / 15 × rtf (15 chars per second of speech is a defaults.md entry; labelled an estimate; null if the rtf is unknown).
 - catalog.get gains an OPTIONAL param {char_count: int ≥ 0}; it doesn't touch the URL, so T03.2's no-URL-over-RPC decision still holds.
 - FitRating schema: rating, tier, gpu_index, reason, details, warnings, rtf, estimate_seconds. Replaces fit: Any in the annotated schemas, plus the schema export.
 - Tests: captured nvidia-smi outputs (several GPUs, a GPU name containing a comma, an old driver without compute_cap, none, missing, timeout, garbage); a fit table of fake machines × fake models.
 - Reviewer: Opus (fit defaults, subprocess).
Follow-up: owner opens two Builder sessions (neither on Claude Opus).

### E-0145 · 2026-11-26 14:14 (Asia/Colombo) · T02.6 · REVIEW-PROMPT
Context: T02.6 round-1 handoff (Antigravity / Gemini), PR #21 `task/T02.6-chunking` @4e78bfa. Verified by the Orchestrator:
 - 3 commits on 96125f8 (an ancestor); mergeable and clean; CI green 12/12; no secrets;
 - 7 files, +1103/−9: chunk.py +377, test_chunk.py +675, the lexicon.py İ fix (_ci_key maps "i\u0307" → "i"; the pragma removed), lexicon tests +35, defaults.md, SPEC.md (3 T02.6 rows plus the index tick).
The Builder reports 420 passed. PR #22 (T03.3) is also open; its handoff has not been pasted yet.
Points noted:
 (a) The 10k-paragraph benchmark is 27.4 s. That's acceptable for import, but render.plan is a SYNC RPC (B8): if T05.4 re-runs chunk_paragraph (including pysbd) per max_chars, planning a novel would block for many seconds. So where does the time go (pysbd vs dialogue/packing)? Can chunks be packed from stored sentences?
 (b) The Builder weakened the reconstruction acceptance check: exact " ".join for space-delimited prose, but only non-whitespace equality where a split falls between non-whitespace characters (CJK, hard splits, quote punctuation). That is a sensible correction (joining CJK chunks with spaces would insert spaces), but it is not recorded in Appendix 3.
 (c) Builder decisions accepted: the ParagraphChunks NamedTuple; rejecting pysbd splits at non-whitespace boundaries unless after a CJK terminator, and rejecting orphan closing-quote segments (fallback plus warning); keeping closing quotes attached at ;/:/, splits; the Greek final-sigma test variants for R1-2.
Decision: Send to a fresh Claude Opus Reviewer. FOCUS:
 - the pipeline and dialogue rules vs E-0144 (continued speech; the „“ language set; the ≥ 2 words/characters rule; flagged cases);
 - the reconstruction rule (b): the strict rule must hold wherever a boundary falls at whitespace; the refined rule must be recorded;
 - performance (a): profile it, and report whether T05.4 needs a sentence-level packing entry point;
 - no chunk over max_chars, including hard splits and combining marks;
 - the pysbd fallback triggers;
 - the İ fix (no new collisions; length is part of the key);
 - tests are meaningful (mutations);
 - Appendix 3 and defaults.md match E-0144.
Follow-up: owner runs the Reviewer.
