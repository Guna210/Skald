# Orchestrator state — snapshot

Last updated: 2026-11-13 13:17 (Asia/Colombo) · last entry: E-0040
Current log file: `CONTEXT.md` (entries E-0001 onward)

## Where the project is
- Phase 0: T00.1, T00.2, T00.3 merged; T00.3 [REVIEW] gate fully signed (E-0032, E-0036). T00.4 PR #5 in review round 1 (E-0039), CI green.
- Phase 1: T01.1 PR #6 built; review deferred until after T00.4 merges and T01.1 rebases (E-0040).
- `master` at `b2bfeb8`. Default branch `master`; spec v1.0 approved (E-0005). Merge method: normal merge (E-0021).
- Open PRs: PR #5 T00.4 (https://github.com/Guna210/Skald/pull/5) — in review round 1, CI green. PR #6 T01.1 (https://github.com/Guna210/Skald/pull/6) — waiting: rebase after T00.4 merges, then review (E-0040).
- Releases/tags: `deps-v1` (Pre-release, 8 assets, verified E-0036).
- Milestones reached: none (next: M1 after T05.8).

## Tasks
- Merged: T00.1 (PR #2), T00.2 (PR #3), T00.3 (PR #4).
- In review: T00.4 (PR #5, round 1, E-0039).
- Waiting: T01.1 (PR #6) — rebase prompt after T00.4 merges, then a new Reviewer prompt (E-0038 withdrawn, E-0040).
- Merge order: T00.4 first, then T01.1 rebases and must show the core job green on both OSes (E-0038).
- After T01.1: T01.2, T01.6, T02.1, T03.9 in parallel; T03.4 needs T01.1 + T00.3. After T00.4: T06.1 (app scaffold) can start.

## Waiting on the owner
1. Paste the T00.4 Reviewer prompt into a fresh Claude Sonnet session (E-0039).
3. Optional: run `.\scripts\setup.ps1` twice on the laptop (T00.4 CI covers it).

## Pending GPU runs
None.

## Open questions from Builders / Reviewers
None.

## Deferred findings
- R1-1 (T00.1, Nit): docs/defaults.md C1.1 item 5 should say alt text / note bodies are skipped "by default". Fix in T02.3 (E-0011).
- R5-2 (T00.3, Nit): redundant exception classes in fetch_deps.py except lists — trim when the file is next touched (E-0031).
- Open item: who creates `core/requirements.lock` (B3)? Not T01.1. Decide by T04.1/T09.1 (E-0020).

## Decisions not yet written into SPEC.md
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
- T09.1: exclude vendor/*/.tmp-*, .old-*, vendor/.downloads, and ffplay/doc/man (ffmpeg binaries 132–143 MB each; vendor/ffmpeg ~400 MB vs 600 MB limit) (E-0027).
- uv mirror assets have no version in the name → a uv bump needs a new mirror tag (deps-v2) (E-0027). Mirror releases are marked Pre-release, never "latest" (E-0034).
- T09.4: ffmpeg is LGPL-3.0-or-later (`--enable-version3`); ship the LGPL-3.0 text + source link (E-0024).
- T09.2: confirm the CLEANUP.md user-data paths once productName is set (E-0009).

## Recommended next step
T00.4 verdict → if approved, owner merges PR #5 → rebase prompt to the T01.1 Builder → check CI on PR #6 → T01.1 Reviewer prompt (updated, with CI).
