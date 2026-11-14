# Orchestrator state — snapshot

Last updated: 2026-11-14 11:00 (Asia/Colombo) · last entry: E-0072
Current log file: `CONTEXT2.md` (E-0058 onward). Older: `CONTEXT.md` (E-0001 … E-0057).

## ★ IMPORTANT (owner, E-0066)
**T03.4 is the task marked IMPORTANT.** If the owner asks "what was the task marked important?" → answer **T03.4** (engine pack spike, [SPIKE][STRONG MODEL][REVIEW]). Owner first deferred it to the end of the week, then asked for the prompt the same night (E-0068); being run on Claude Code cloud (Opus). Keep this note until T03.4 is merged.

## Where the project is
- **Phase 0 complete** (T00.1–T00.4 merged; E-0046). CI runs on every push/PR on windows-latest + ubuntu-latest.
- Phase 1: T01.1, T01.2 merged. T02.1 merged (PR #8). T01.4 and T01.6 building in parallel (E-0067). T03.4 (★) APPROVED + gate signed off; owner to merge PR #11 (E-0072).
- `master` at `5a85aac`. Default branch `master`; spec v1.0 approved (E-0005). Merge method: normal merge (E-0021).
- Open PRs: #11 T03.4 (APPROVED round 2 at 653f202, CI green, gate signed off; owner to merge, E-0072). T01.4/T01.6 branches exist (PRs #9/#10 presumably); handoffs not yet received.
- Releases/tags: `deps-v1` (Pre-release, 8 assets, verified E-0036).
- Milestones reached: none (next: M1 after T05.8).

## Tasks
- Merged: T00.1 (PR #2), T00.2 (PR #3), T00.3 (PR #4), T00.4 (PR #5), T01.1 (PR #6), T01.2 (PR #7), T02.1 (PR #8).
- Building (round 1, prompts issued E-0067): T01.4 schemas + system.info (`task/T01.4-schemas-system-info`), T01.6 HTTP helper (`task/T01.6-http-downloader`). Whichever merges second rebases (Appendix 3 rows).
- Round 2 (E-0070): T03.4 ★IMPORTANT engine-pack spike, PR #11 (Builder Claude Fable 5.2; Reviewer Claude Opus). Fix R1-1…R1-4 + apply gate decisions G1–G14 to SPEC (B5, B7, B9, C2, Appendix 4, T03.5, Appendix 3). APPROVED round 2 at 653f202; [REVIEW] gate signed off (E-0072). Owner to merge.
- Available, not started (prompt only when the owner asks; E-0057): T02.2 EPUB container/spine/nav, T03.7 worker protocol, T03.9 [SPIKE][REVIEW], T06.1.
- T01.3 job manager becomes available after T01.4 merges (E-0056).

## Waiting on the owner
1. Run the T01.4 and T01.6 Builders and send back their handoffs (E-0067).
2. Merge PR #11 (T03.4, normal merge) and confirm (E-0072).
3. Later, before any non-Claude agent builds a pack task: add `download-r2.pytorch.org` to that agent's cloud environment (already in the owner's Claude env) (E-0069).

## Pending GPU runs
None.

## Open questions from Builders / Reviewers
None (T03.4 proposal 12: owner said yes, E-0070).

## Deferred findings
- R2-1, R2-2 (T01.2, Nits) → in the T01.4 prompt (issued E-0067); check they're done in its review.
- T02.1 R2-1 (Nit): unused "font_obfuscation" alias + include_font/font_href fallback in make_epubs.py — trim when the file is next touched (E-0063).
- T02.1 R2-2 (Nit) → T02.2 prompt: assert only status/error kind for epub_invalid (12) and epub_drm (10) fixtures (E-0063).
- R1-1 (T00.1, Nit): docs/defaults.md C1.1 item 5 should say alt text / note bodies are skipped "by default". Fix in T02.3 (E-0011).
- R5-2 (T00.3, Nit): redundant exception classes in fetch_deps.py except lists — trim when the file is next touched (E-0031).
- Open item: who creates `core/requirements.lock` (B3)? Not T01.1. Decide by T04.1/T09.1 (E-0020).

## Decisions not yet written into SPEC.md
- E-0049 T02.1: TOML defs + ZIP_STORED — recorded in PR #8's Appendix 3 rows (on master once #8 merges).
- E-0061 D1–D4 — recorded in PR #8's Appendix 3 rows (on master once #8 merges).
- E-0056 + E-0067 T01.4 / T01.6 decisions — recorded by those Builders in their PRs (check in review).
(All earlier decisions are on master: E-0020, E-0021, E-0032, E-0033, E-0048, E-0049 T01.2 rows, E-0052 rows.)

## Standing notes for prompts
- **Owner rule (E-0057): after a task completes, only list the available tasks; give a Builder prompt only when the owner asks.** Review/fix/rebase prompts for in-flight work are still given normally.
- Builder prompts: owner authorizes pushing to `task/<ID>-<slug>` and opening a PR, even if a Claude cloud session got a `claude/…` branch (E-0004). Reviewer prompts: read-only, no pushes or PR comments.
- `<owner>` in the spec = `Guna210`.
- Merge method: normal merge ("Create a merge commit"), owner decision (E-0021). Never tell the owner to squash.
- Handoffs and verdicts may arrive as cross-session messages or not at all; verify against the PR before acting (E-0009, E-0030).
- Every Builder prompt that runs npm/pip: source `scripts/dev-env.*` first; there is no `.npmrc` (E-0016).
- fetch_deps.py is run with the venv Python (`core/.venv`), never bare `python3` (E-0027 R4-5).
- Future mirror uploads (deps-v2…): verify every asset from the cloud against the doc (method in E-0031/E-0036).
- T02.3 prompt: include deferred R1-1 (E-0011).
- T02.2/T02.3 prompts: E-0061 D1 (recover=True for malformed content XHTML with step-7 flags; structural files → epub_invalid), D2 (rule-4 char count), D3 (cumulative skip_reasons), D4 (linear="no" separate from skips). T02.2 owns the entity-expansion fixture (rule 7).
- T06.1: setup-node@v7 defaults `package-manager-cache: true` — confirm no clash with the .cache/npm cache step (E-0044).
- T06.1: setup.* will run `npm ci` inside the CI core/worker jobs once app/package-lock.json exists (no npm cache there) — decide then (E-0041).
- T03.7: worker/pyproject.toml must land with ≥1 test, or CI pytest exits 5 (E-0041).
- T03.5: CI `.cache/uv` key covers only deps.lock.json — add pack lockfiles (E-0041).
- T03.5 prompt: build it from docs/spikes/engine-packs.md §4 + gate decisions G1–G14 (E-0070, in SPEC once PR #11 merges): copy bundled Python to <storage>/python/<ver>/, clean-only-when-empty, try `uv cache clean <pkg>`, cu126 min driver with source, fake-uv tests per G10; F1 storage resolution (SKALD_STORAGE_DIR → <SKALD_DEV_DATA>/storage → platform default) + Appendix 3 row + T06.2 env line; F2 fix the Part B diagram host wording (E-0071).
- T06.2 prompt: core.ts passes SKALD_STORAGE_DIR only when the user chose a storage folder (F1, E-0071).
- T03.5 prompt also carries T03.4 R2 leftovers (E-0072): R2-1 guard in docs/spikes/scripts/notes.sh (refuse an existing non-empty folder); R2-2 T07.10 add "move (or re-copy) python/"; R2-3 engine-packs.md:139 "section 3.9" → 3.10; R2-4 cite NVIDIA CUDA 13 notes in the Appendix 3 Pascal row; (a) T06.2 env line per F1; (b) C4 dev pack location → `<SKALD_DEV_DATA>/storage/`.
- T07.10: storage-folder move per G11; default storage = %LOCALAPPDATA%\Skald / ~/.local/share/Skald (G3) (E-0070).
- T09.4: NVIDIA terms for GPU packs in third-party notices; T09.2: CLEANUP.md must also list the new default storage folder (G3) (E-0070).
- Never mirror/redistribute pack wheels anywhere (owner, G12) (E-0070).
- Catalog/adapter tasks: don't promise Pascal (sm_61) until confirmed on a real card; a future cu13 accelerator drops Pascal/Volta (D9 impact) (E-0069).
- T09.1: test fixtures (core/tests/data, incl. Gutenberg EPUBs) are never packaged (E-0060).
- T09.1: exclude vendor/*/.tmp-*, .old-*, vendor/.downloads, and ffplay/doc/man (ffmpeg binaries 132–143 MB each; vendor/ffmpeg ~400 MB vs 600 MB limit) (E-0027).
- uv mirror assets have no version in the name → a uv bump needs a new mirror tag (deps-v2) (E-0027). Mirror releases are marked Pre-release, never "latest" (E-0034).
- T03.7 prompt: evaluate an fd-level stdout redirect (os.dup/os.dup2) in workers; model libraries may print from C code (E-0052).
- Every prompt that launches subprocesses (T01.3, T03.5, T03.8, T05.6…): never inherit stdout — pass stdout= explicitly (Appendix 3 rule from T01.2) (E-0052).
- T01.3 prompt: use JobRef from T01.4's schemas; unknown job_id → -32602 kind internal; job.finished never throttled; cancel while paused unblocks checkpoint() and raises JobCancelled; subprocesses pass stdout explicitly (E-0056).
- T03.6 prompt: map net.DownloadCancelled → JobCancelled (E-0056).
- T02.2/T02.3/T02.8 prompts: the spec's "YAML" fixture definitions are TOML files read with tomllib (E-0049).
- pysbd 0.3.4 emits SyntaxWarning under 3.12 → any `filterwarnings = error` needs a scoped ignore (E-0048).
- T09.1/T09.4: soundfile bundles libsndfile (LGPL-2.1) → ship its licence + source link (E-0048).
- T09.4: ffmpeg is LGPL-3.0-or-later (`--enable-version3`); ship the LGPL-3.0 text + source link (E-0024).
- T09.2: confirm the CLEANUP.md user-data paths once productName is set (E-0009).

## Recommended next step
Process the T01.4 / T01.6 handoffs (verify PR + CI, Reviewer prompts; T01.4 reviewer should check R2-1/R2-2 carry-overs and the E-0067 ffmpeg rules).
