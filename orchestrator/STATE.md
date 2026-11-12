# Orchestrator state — snapshot

Last updated: 2026-11-12 23:41 (Asia/Colombo) · last entry: E-0008
Current log file: `CONTEXT.md` (entries E-0001 onward)

## Where the project is
- Phase 0 started: T00.1 assigned (round 1), not yet picked up by a Builder.
- `master` at `db7a0d9` (PR #1 merged): `AGENTS.md`, `CLAUDE.md`, `SPEC.md` only. Default branch `master` (E-0005); spec v1.0 approved (E-0005).
- Open PRs: none. Releases/tags: none (`deps-v1` mirror comes with T00.3).
- Milestones reached: none (next: M1 after T05.8).

## Tasks
- Merged: none.
- In progress: **T00.1 Repository scaffolding** — round 1, prompt issued (E-0008), branch `task/T00.1-repo-scaffolding`.
- Next after T00.1: T00.2 and T00.3 in parallel (both depend only on T00.1); T00.4 needs both. T00.3 is [REVIEW] and needs the owner to create the `deps-v1` release.
- Also unlocked by T00.2 alone: T01.1 → then T01.x, T02.1, T03.9 can start in parallel.

## Waiting on the owner
1. Open a Builder session and paste the T00.1 prompt (E-0008).

## Pending GPU runs
None.

## Open questions from Builders / Reviewers
None.

## Decisions not yet written into SPEC.md
- E-0008 T00.1 clarifications (B3 vs Do list, LICENSE copyright line) — the T00.1 Builder records them in Appendix 3.

## Standing notes for prompts
- Builder prompts: state that the owner authorizes pushing to `task/<ID>-<slug>` and opening a PR, even though a Claude cloud session is given a `claude/…` branch by default (E-0004). Reviewer prompts: read-only, no pushes.
- `<owner>` in the spec = `Guna210`.
- T00.2 prompt: also create the root `.npmrc` (B3; nothing else creates it) — npm cache under `.cache/npm` (E-0008).
- Remind the owner to use "Squash and merge" (PR #1 was merged with a merge commit; E-0007).
- Ponytail pinned commit verified reachable (E-0007).

## Recommended next step
Owner runs the T00.1 Builder. When the handoff comes back: sanity-check it, then issue `PASTE TO: REVIEWER · T00.1` (fresh Claude session, Sonnet; a different model from the Builder's if the Builder was Claude).
