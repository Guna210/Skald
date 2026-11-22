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
