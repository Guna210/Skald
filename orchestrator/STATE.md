# Orchestrator state — snapshot

Last updated: 2026-11-13 00:38 (Asia/Colombo) · last entry: E-0021
Current log file: `CONTEXT.md` (entries E-0001 onward)

## Where the project is
- Phase 0: T00.1 merged. T00.2 APPROVED round 2 (PR #3), merge pending. T00.3 assigned, building (no branch pushed yet).
- Phase 1: T01.1 prompt issued (paste after PR #3 merges).
- `master` at `3e4a81d`. Default branch `master`; spec v1.0 approved (E-0005).
- Open PRs: PR #3 T00.2 (https://github.com/Guna210/Skald/pull/3) — APPROVED round 2 (E-0019), merge pending.
- Releases/tags: none (`deps-v1` mirror comes with T00.3).
- Milestones reached: none (next: M1 after T05.8).

## Tasks
- Merged: T00.1 (PR #2).
- Approved, merge pending: T00.2 (PR #3).
- Assigned (round 1): T00.3 pinned binaries [REVIEW] (E-0012, building); T01.1 core package skeleton (E-0020, not started).
- Next: T00.4 after T00.3. After T01.1: T01.2, T01.6, T02.1, T03.9 in parallel; T03.4 also needs T00.3.

## Waiting on the owner
1. Merge PR #3 (normal merge) (E-0019, E-0021). Optional: run `.\scripts\setup.ps1` twice on the laptop.
2. Then paste the T01.1 prompt into a Builder session (E-0020).
3. Bring the T00.3 handoff when it arrives.

## Pending GPU runs
None.

## Open questions from Builders / Reviewers
None.

## Deferred findings
- Open item: who creates `core/requirements.lock` (B3)? Not T01.1. Decide by T04.1/T09.1 (E-0020).
- R1-1 (T00.1, Nit): docs/defaults.md C1.1 item 5 should say alt text / note bodies are skipped "by default". Fix in T02.3 (E-0011).

## Decisions not yet written into SPEC.md
- E-0021 normal merge instead of squash — CLAUDE.md lines 45 and 99 still say squash; fix via the next Builder PR.
- E-0020 T01.1 clarifications (CI criterion timing, requirements.lock not created, no-arg behaviour) — the T01.1 Builder records them.
- E-0012 clarifications (T00.2 `.npmrc` placement, setup.ps1 Python lookup; T00.3 unittest-style tests, ffmpeg build choice, safe extraction) — the T00.2/T00.3 Builders record them.

## Standing notes for prompts
- Builder prompts: owner authorizes pushing to `task/<ID>-<slug>` and opening a PR, even if a Claude cloud session got a `claude/…` branch (E-0004). Reviewer prompts: read-only, no pushes or PR comments.
- `<owner>` in the spec = `Guna210`.
- Handoffs and verdicts may arrive as cross-session messages; verify against the PR before acting (E-0009).
- Merge method: normal merge ("Create a merge commit"), owner decision (E-0021). Never tell the owner to squash.
- Next Builder prompt issued: also change CLAUDE.md line 45 ("Use **Squash and merge**") and line 99 (merge steps) to the normal merge, plus an Appendix 3 row (E-0021).
- T00.4 prompt: CI must also run `scripts/tests` (unittest-style, from T00.3) (E-0012); source dev-env before any npm/pip call; watch for Windows PowerShell 5.1 + `$ErrorActionPreference=Stop` turning native stderr (pip) into errors (E-0016).
- Every Builder prompt that runs npm: source `scripts/dev-env.*` first — there is no `.npmrc` (E-0016).
- T00.2/T00.3 run in parallel: the second to merge needs a rebase on master (E-0012).
- T02.3 prompt: include deferred R1-1 (E-0011).
- T09.2: confirm the CLEANUP.md user-data paths once productName is set (E-0009).

## Recommended next step
Owner merges PR #3 and starts T01.1. On the T00.3 handoff: it must rebase on master (conflicts in SPEC ticks / Appendix 3 / AGENTS.md Part 5), then review. On the T01.1 handoff: same rebase check if T00.3 merged first.
