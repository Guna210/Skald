# Orchestrator state — snapshot

Last updated: 2026-11-12 23:31 (Asia/Colombo) · last entry: E-0004
Current log file: `CONTEXT.md` (entries E-0001 onward)

## Where the project is
- Phase 0 has not started. No task is merged, in progress or assigned.
- Repo: 2 commits; only `AGENTS.md`, `CLAUDE.md`, `SPEC.md` (v1.0, 16 Oct 2026).
- Default branch is `master` (docs assume `main`) — see "Waiting on the owner".
- Open PRs: none. Releases/tags: none (`deps-v1` mirror not created yet).
- Milestones reached: none (next: M1 after T05.8).

## Tasks
- Merged: none.
- In progress: none.
- Next: **T00.1 Repository scaffolding** (S, no dependencies, cloud, any Builder agent, standard model).
- After T00.1: T00.2 and T00.3 can run in parallel (both depend only on T00.1); T00.4 needs both.

## Waiting on the owner
1. Rename the default branch `master` → `main` on GitHub (E-0002). Blocks T00.1.
2. Confirm `SPEC.md` v1.0 is approved (header still says "Draft for owner approval") (E-0003).

## Pending GPU runs
None.

## Open questions from Builders / Reviewers
None.

## Decisions not yet written into SPEC.md
- If the owner approves the spec: T00.1 Builder changes the status line to "Approved" and adds an Appendix 3 row (E-0003).

## Standing notes for prompts
- Builder prompts: state that the owner authorizes pushing to `task/<ID>-<slug>` and opening a PR, even though a Claude cloud session is given a `claude/…` branch by default (E-0004).
- T00.1: create B3 directories plus only the files in T00.1's Do list; stop and ask if the pinned Ponytail commit can't be fetched (E-0004).
- `<owner>` in the spec = `Guna210`.

## Recommended next step
Owner does the two items above, then says "What's next?" → issue `PASTE TO: BUILDER · T00.1`.
