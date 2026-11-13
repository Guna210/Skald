# Orchestrator state — snapshot

Last updated: 2026-11-13 15:37 (Asia/Colombo) · last entry: E-0053
Current log file: `CONTEXT.md` (entries E-0001 onward)

## Where the project is
- **Phase 0 complete** (T00.1–T00.4 merged; E-0046). CI runs on every push/PR on windows-latest + ubuntu-latest.
- Phase 1: T01.1 merged (E-0050). T01.2 PR #7 CHANGES REQUESTED round 1 (1 Major); fix round 2 issued (E-0052, E-0053). T02.1 building (branch pushed, no handoff yet).
- `master` at `e3327d8`. Default branch `master`; spec v1.0 approved (E-0005). Merge method: normal merge (E-0021).
- Open PRs: PR #7 T01.2 (https://github.com/Guna210/Skald/pull/7) — fix round 2 in progress (E-0053).
- Releases/tags: `deps-v1` (Pre-release, 8 assets, verified E-0036).
- Milestones reached: none (next: M1 after T05.8).

## Tasks
- Merged: T00.1 (PR #2), T00.2 (PR #3), T00.3 (PR #4), T00.4 (PR #5), T01.1 (PR #6).
- In fix round: T01.2 (PR #7, round 2, E-0053), then re-check by the same Reviewer.
- Building: T02.1 EPUB fixtures (E-0049).
- Also ready, not yet assigned: T01.6, T03.9 [SPIKE][REVIEW], T03.4 [SPIKE][STRONG MODEL][REVIEW], T06.1.

## Waiting on the owner
1. Paste the T01.2 round-2 fix prompt into the T01.2 Builder session (E-0053).
2. Bring the T02.1 handoff. Say if you want more parallel tasks.
3. Optional: run `.\scripts\setup.ps1` twice on the laptop (CI covers it).

## Pending GPU runs
None.

## Open questions from Builders / Reviewers
None.

## Deferred findings
- R1-1 (T00.1, Nit): docs/defaults.md C1.1 item 5 should say alt text / note bodies are skipped "by default". Fix in T02.3 (E-0011).
- R5-2 (T00.3, Nit): redundant exception classes in fetch_deps.py except lists — trim when the file is next touched (E-0031).
- Open item: who creates `core/requirements.lock` (B3)? Not T01.1. Decide by T04.1/T09.1 (E-0020).

## Decisions not yet written into SPEC.md
- E-0048 R1-1/R1-2/R1-3 carry-overs and E-0049 T01.2 decisions — the T01.2 Builder records them.
- E-0049 T02.1: TOML fixture definitions (spec says YAML), ZIP_STORED — the T02.1 Builder records them.
- E-0020 T01.1 clarifications — the T01.1 Builder records them.
- E-0021 normal merge; E-0032 T00.3 [REVIEW] sign-off; E-0033 T00.4 decisions — the T00.4 Builder records them (and fixes CLAUDE.md lines 45 and 99).

## Standing notes for prompts
- Builder prompts: owner authorizes pushing to `task/<ID>-<slug>` and opening a PR, even if a Claude cloud session got a `claude/…` branch (E-0004). Reviewer prompts: read-only, no pushes or PR comments.
- `<owner>` in the spec = `Guna210`.
- Merge method: normal merge ("Create a merge commit"), owner decision (E-0021). Never tell the owner to squash.
- Handoffs and verdicts may arrive as cross-session messages or not at all; verify against the PR before acting (E-0009, E-0030).
- Every Builder prompt that runs npm/pip: source `scripts/dev-env.*` first; there is no `.npmrc` (E-0016).
- fetch_deps.py is run with the venv Python (`core/.venv`), never bare `python3` (E-0027 R4-5).
- T00.4 review: CI logs should show "using mirror" for ffmpeg/uv/python (E-0036).
- Mirror verification after upload: download all 8 deps-v1 assets from the cloud and compare with docs/spikes/deps-mirror.md; snapshots may be accepted on the uncompressed tar SHA-256 (E-0031).
- T02.3 prompt: include deferred R1-1 (E-0011).
- T06.1: setup-node@v7 defaults `package-manager-cache: true` — confirm no clash with the .cache/npm cache step (E-0044).
- T06.1: setup.* will run `npm ci` inside the CI core/worker jobs once app/package-lock.json exists (no npm cache there) — decide then (E-0041).
- T03.7: worker/pyproject.toml must land with ≥1 test, or CI pytest exits 5 (E-0041).
- T03.5: CI `.cache/uv` key covers only deps.lock.json — add pack lockfiles (E-0041).
- T09.1: exclude vendor/*/.tmp-*, .old-*, vendor/.downloads, and ffplay/doc/man (ffmpeg binaries 132–143 MB each; vendor/ffmpeg ~400 MB vs 600 MB limit) (E-0027).
- uv mirror assets have no version in the name → a uv bump needs a new mirror tag (deps-v2) (E-0027). Mirror releases are marked Pre-release, never "latest" (E-0034).
- T03.7 prompt: evaluate an fd-level stdout redirect (os.dup/os.dup2) in workers; model libraries may print from C code (E-0052).
- Every prompt that launches subprocesses (T01.3, T03.5, T03.8, T05.6…): never inherit stdout — pass stdout= explicitly (Appendix 3 rule from T01.2) (E-0052).
- T01.4 prompt: SkaldErrorData = { kind, details, hint }; protocol errors use kind `internal` (E-0052).
- T02.2/T02.3/T02.8 prompts: the spec's "YAML" fixture definitions are TOML files read with tomllib (E-0049).
- pysbd 0.3.4 emits SyntaxWarning under 3.12 → any `filterwarnings = error` needs a scoped ignore (E-0048).
- T09.1/T09.4: soundfile bundles libsndfile (LGPL-2.1) → ship its licence + source link (E-0048).
- T09.4: ffmpeg is LGPL-3.0-or-later (`--enable-version3`); ship the LGPL-3.0 text + source link (E-0024).
- T09.2: confirm the CLEANUP.md user-data paths once productName is set (E-0009).

## Recommended next step
Owner merges PR #6 and runs T01.2 + T02.1. Offer T01.6 / T03.9 / T03.4 / T06.1 if the owner wants more in parallel.
