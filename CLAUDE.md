# CLAUDE.md — Session roles for Skald

Work on this project is split into three roles: **Orchestrator**, **Builder** and **Reviewer**.

- **Claude sessions** can take any of the three roles. The owner states the role at the start of the session (for example "You are the Reviewer"). If no role is given, ask which one before doing anything else.
- **Other agents** (Codex, Gemini, Copilot and so on) are always **Builders**.
- **Every Builder, Claude or not, follows `AGENTS.md` Parts 2–4**: its workflow, question and handoff formats, the [GPU] task procedure, and the Ponytail skill. This file covers only the Orchestrator and Reviewer roles, so there is one rulebook for building.

All sessions follow **`AGENTS.md` Part 1** (project rules) and **`SPEC.md`** (what we're building and how). If this file and `SPEC.md` disagree about *what* to build, `SPEC.md` wins. If they disagree about *how sessions work together*, this file wins for the Orchestrator and Reviewer, and `AGENTS.md` for Builders.

---

## How the sessions work together

Sessions can't talk to each other. The owner carries messages between them by copy-paste, and the Orchestrator decides what each message says.

```
Owner ──"what's next?"──▶ Orchestrator ──prompt──▶ (owner pastes) ──▶ Builder
Builder ──question──▶ (owner pastes) ──▶ Orchestrator ──answer──▶ (owner pastes) ──▶ Builder
Builder ──"done" + PR──▶ (owner pastes) ──▶ Orchestrator
    ├─ [GPU] task ──Colab steps──▶ Owner runs the self-test notebook ──report──▶ Orchestrator
    └─ review prompt ──▶ (owner pastes) ──▶ Reviewer
Reviewer ──verdict──▶ (owner pastes) ──▶ Orchestrator
    ├─ CHANGES REQUESTED ──fix prompt──▶ Builder ──▶ … back to Reviewer (next round)
    └─ APPROVED ──▶ Orchestrator tells the owner how to merge ──▶ next task
```

### Message format (all roles)

Anything meant to be pasted into another session goes in **one fenced code block**, and the first line of the block says where it goes:

```
PASTE TO: BUILDER · T03.3
...
```

Valid destinations: `PASTE TO: ORCHESTRATOR`, `PASTE TO: BUILDER · <task>`, `PASTE TO: REVIEWER · <task>`. Text outside the block is for the owner only and should be short, plain-language guidance (for example "Open a new session with Sonnet and paste this"). Never split one message across several blocks, and never put two destinations in one block.

### Git conventions

- One task = one branch = one pull request (PR).
- Branch name: `task/<ID>-<short-slug>`, for example `task/T00.1-repo-scaffolding`.
- PR title: `<ID>: <task title>`, for example `T00.1: Repository scaffolding`.
- Builders branch from the latest `main` and never push to `main` directly.
- A PR is merged only after the Reviewer says **APPROVED**, CI is green and, for **[GPU]** tasks, the owner's self-test report passes. Use **Squash and merge**.
- Fix rounds push new commits to the same branch and PR.
- The branch `orchestrator` holds only the Orchestrator's memory files (see "Orchestrator memory" below). It is never merged into `main`, and Builders and Reviewers never commit to it.

### Skills (Ponytail)

Two skills from [Ponytail](https://github.com/DietrichGebert/ponytail) (MIT) are copied into the repo, pinned to commit `84740e3d344b69b4a133201fa519eb37a62a2b2a`, so they work in every session, including cloud sessions, without anything installed globally:

- `.agents/skills/ponytail/` — **required for every Builder**, Claude included. It makes them write the smallest complete change. How they load it, and the rule that `SPEC.md` always takes precedence over it, are in `AGENTS.md` Part 3.
- `.claude/skills/ponytail-review/` — **optional for Claude Reviewers**, as an extra lens for bugs, risk, missing tests and unnecessary code (see Role 2 below).

Only the skill files are copied, not Ponytail's plugin hooks, status line or commands.

---

## Role 1 — Orchestrator

**Purpose:** plan, coordinate and decide. The Orchestrator does not write product code and does not review code line by line. It turns the spec into prompts for Builders and Reviewers, answers their questions, and keeps the project moving in the right order.

**Authority:** the Orchestrator has the same authority as the owner. It may answer any question, approve deviations from the spec, change decisions in the spec's decision log, re-split tasks, approve new text/audio defaults and intelligibility thresholds, and sign off **[REVIEW]** checks. It should still say plainly when an outside expert (for example someone who knows audio production or open-source licensing) would add real value, and it must **ask the owner** before anything that only a human can or should do:
- spending money (including renting a GPU), creating accounts, entering credentials or changing GitHub settings;
- installing anything globally on the owner's laptop (and then make sure it's added to `CLEANUP.md`);
- legal and licensing judgments with real consequences — above all, reading a **non-commercial model's license** (T04.7) and accepting any license on the owner's behalf — and applying to external programmes (e.g. SignPath);
- publishing a release, creating GitHub releases (e.g. the `deps-v1` mirror), or deleting data or branches that can't be recovered;
- hands-on checks only the owner can do: running the GPU self-test notebook, clicking through the app on Windows, and listening reviews.

### What the Orchestrator does when the owner says…

**"What's next?"**
1. Work out the current state: read `STATE.md` on the `orchestrator` branch, then confirm it against the repo — which tasks are merged (the ticked boxes in `SPEC.md` Part D on `main`), which PRs are open, and anything still waiting on the owner (GPU runs, reviews, mirror uploads). If they disagree, trust the repo and log a correction.
2. Pick the next task: the lowest-numbered unticked task whose dependencies are all merged and whose **[REVIEW]** gates are cleared. If several independent tasks are ready and the owner wants to go faster, offer to run them in parallel in separate Builder sessions.
3. Reply with:
   - one line for the owner: which builder agent to open (any of the owner's agents, Claude included, using its strongest available model for **[STRONG MODEL]** tasks) and where (cloud or laptop — see "Where to run" below);
   - one `PASTE TO: BUILDER · <ID>` block using the Builder prompt template below.

**A pasted Builder or Reviewer question**
- Answer every question directly and decisively. Give a recommendation, not a menu, unless the owner must choose.
- If the answer clarifies or changes the spec, say so inside the paste block and tell the Builder to record it in `SPEC.md` **Appendix 3 — Clarifications log** (and in the decision log if it's a decision) as part of the same PR. This keeps the spec the single source of truth.
- If the question is really a license question (what a model's terms allow, whether a dependency's license is compatible), give your reading, and for anything about a non-commercial model, ask the owner to confirm before the Builder proceeds.
- Reply with one paste block back to the session that asked.

**"Builder is done" (a pasted Builder handoff)**
- Sanity-check the handoff (format in `AGENTS.md` Part 4): acceptance criteria claimed, tests run, shortcuts listed, catalog changes listed, nothing unexplained. If something obvious is missing, send it back to the Builder first.
- **If the task is marked [GPU]** (or the handoff lists GPU SELF-TEST NEEDED), give the owner the GPU steps (see "GPU self-test steps for the owner" below) before or alongside the review. A [GPU] task is not merged without a passing report.
- Otherwise, or in parallel, reply with a `PASTE TO: REVIEWER · <ID>` block using the Reviewer prompt template below, including anything the Reviewer should look at extra carefully (defaults touched, catalog entries, licenses, earlier findings, the GPU report once available).
- Recommend a **fresh Claude session** for the Reviewer: Sonnet by default; Opus for **[STRONG MODEL]** tasks, catalog changes, adapters and anything touching licenses or defaults. If the Builder was Claude, use a different Claude model from the Builder's where possible.

**A pasted GPU self-test report**
- Check every listed checkpoint: installed, loaded, all passages under their thresholds, QC passed, VRAM and RTF recorded.
- First run of a new model: thresholds don't exist yet. Approve or adjust the proposed thresholds (first run + margin, SPEC C3.5) and send the Builder a fix prompt to record them and the measured numbers. Later runs: thresholds are fixed; a failure goes back to the Builder as a finding, never as a threshold change, unless you decide the threshold itself was wrong and record why.
- Pass the report to the Reviewer as part of FOCUS.

**A pasted Reviewer verdict**
- **CHANGES REQUESTED:** decide which findings must be fixed now. Blockers and majors normally are; minors and nits can be accepted, deferred to a later task, or dropped — say which. Reply with a `PASTE TO: BUILDER · <ID>` fix prompt listing the findings to fix by their IDs.
- **APPROVED:** tell the owner in plain steps how to merge the PR (open the PR link → check CI is green → for [GPU] tasks, check the self-test report is attached → "Squash and merge" → "Confirm"), then list any follow-ups and offer the next task.
- **Round limit:** if a task reaches a third round of changes requested, stop and rethink: re-split the task, clarify the spec, or switch the Builder to a stronger model.

**[REVIEW] gates**
- When a task marked **[REVIEW]** is approved, perform the check yourself (for example read `scripts/deps.lock.json`, `docs/verification/text-review.md`, a spike's findings, or the proposed thresholds) and record the sign-off in the clarifications log via the next PR. Ask the owner when the gate needs a human: the mirror upload (T00.3), the text-extraction skim (T02.8), the non-commercial license reading (T04.7), the GPU runs (T08.2) and the listening review (T08.3).

**Owner-only steps**
- When a task needs the owner (Windows hand-testing, GPU runs, GitHub releases or settings, installs, listening), give short numbered instructions written for a non-developer, including what "success" looks like.

**Handoff to a new Orchestrator session**
- Because everything is in the memory files below, a new Orchestrator session only needs to be told "You are the Orchestrator" — it will read `STATE.md` and the current `CONTEXT` file itself. Only if a session can't reach the repo, produce a `PASTE TO: ORCHESTRATOR` block containing the current `STATE.md`.

### GPU self-test steps for the owner

When a [GPU] task is ready, give the owner steps like these (fill in the branch and models):

1. Open the "Open in Colab" link from `CONTRIBUTING.md` (it opens `selftest/selftest.ipynb` from `main`). If the PR itself changed the notebook, instead use Colab's **File → Open notebook → GitHub**, paste the repo URL, choose the PR branch and the notebook.
2. In the first cell, set `BRANCH = "task/<ID>-<slug>"` and `MODELS = [<ids from the handoff>]`.
3. **Runtime → Change runtime type → T4 GPU**, then **Runtime → Run all**. If Colab gives no GPU, try again later or use the same notebook on Kaggle.
4. Don't mount Google Drive and don't paste any tokens.
5. When it finishes, copy the contents of the "Report" cell (or download `report.md`) and paste it here. Success looks like every row saying PASS.

If a model doesn't fit on a T4, say so to the owner and ask before suggesting a rented GPU (it costs money).

### Orchestrator memory (branch `orchestrator`)

The Orchestrator keeps a permanent record of everything it decides, so it can get back up to speed after its context is compacted or a new session starts. This requires the Orchestrator session to have access to the GitHub repo (run it as a Claude Code session connected to `Skald`).

**Branch.** `orchestrator` is created once, as an *orphan* branch (`git switch --orphan orchestrator`), so it contains only the memory files and none of the code. The Orchestrator reads the spec and code from `main` (e.g. `git show origin/main:SPEC.md`) and writes only to `orchestrator`. It is never merged anywhere.

**Files** (in the folder `orchestrator/` on that branch):

| File | What it is | How it changes |
|---|---|---|
| `STATE.md` | A short snapshot of *right now*: tasks merged, task in progress and its round, open PRs, pending GPU runs, open questions, decisions not yet written into `SPEC.md`, items waiting on the owner, the recommended next step, and which `CONTEXT` file is current. Keep it under ~150 lines. | Rewritten on every update (it's a snapshot, not a log). |
| `CONTEXT.md`, `CONTEXT2.md`, `CONTEXT3.md`, … | The running log: every task assigned, question answered, decision made, GPU report processed, verdict processed, merge confirmed and owner action requested, with the reasoning. | **Append-only.** Earlier entries are never edited or trimmed. A mistake is corrected by a new entry that refers to the old one. |

**Entry format** (entries are numbered across all files, so numbers never restart):

```
### E-0042 · 2026-10-16 14:05 (Asia/Colombo) · T04.4 · ANSWER
Context: Builder asked whether Chatterbox Nano needs a reference clip for preset voices.
Decision: Yes — use the Kokoro-derived starter clips from SPEC T04.4.
Why: Nano/Turbo clone from a reference; the spec already provides starter voices.
Follow-up: none.
```

Entry types: `TASK-ASSIGNED`, `QUESTION`, `ANSWER`, `DECISION`, `REVIEW-PROMPT`, `GPU-RUN`, `VERDICT`, `FIX-PROMPT`, `MERGED`, `REVIEW-GATE`, `OWNER-ACTION`, `CORRECTION`, `NOTE`. Summarize what was pasted rather than copying long blocks in full, but keep every decision, every measured number that drove a decision, and its reason.

**No secrets.** The repo is public, so the memory files are too. Never write tokens, passwords or other credentials into them.

**When to write.** After every exchange that changes the project's state, before replying to the owner: append the entry, update `STATE.md`, then commit and push to `orchestrator` with a message like `log: E-0042 T04.4 answer`. If a push fails, tell the owner rather than carrying on silently.

**When a CONTEXT file gets long.** When the current file passes about **1,000 lines (~50 KB)**, start the next one (`CONTEXT2.md`, then `CONTEXT3.md`, and so on). Nothing is trimmed or moved. Each new file starts with a header giving its number, the first entry number it contains, and the previous file's name; `STATE.md` records which file is current.

**After a compaction or at the start of a new session:**
1. Fetch the repo and read `orchestrator/STATE.md`.
2. Read the current `CONTEXT` file in full.
3. Check `main` and open PRs; if anything disagrees with `STATE.md`, trust the repo and add a `CORRECTION` entry.
4. Look up older history only when needed, by searching the older `CONTEXT` files (e.g. `git grep "T04.5"`), instead of reading them all.

### Where to run

- **Cloud sessions (Claude Code cloud / Codex cloud, Linux, no GPU):** default for the core, the worker, catalog work, CPU packs, CI and most app code.
- **Owner's laptop (Windows, no NVIDIA GPU):** when a task needs Windows-specific checks or the running app. Cloud sessions can't open the app's window; for UI tasks the Builder works in the cloud and the Orchestrator then gives the owner a short manual test to run on the laptop before merging.
- **Colab or Kaggle (T4 GPU):** only the owner, only through the self-test notebook, for [GPU] tasks and release checks. Builders for [GPU] tasks still work in the cloud.

### Builder prompt template (Orchestrator fills this in)

```
PASTE TO: BUILDER · <ID>
ROLE: Builder
TASK: <ID> — <title>
BRANCH: task/<ID>-<slug>  (create from the latest main)
ROUND: 1
READ: AGENTS.md (all parts), SPEC.md Parts A–C and task <ID> in Part D. Load the Ponytail skill as described in AGENTS.md Part 3.
EXTRA CONTEXT: <clarifications, answers already given, relevant earlier decisions — or "none">
WATCH OUT FOR: <specific risks for this task — or "none">
GPU: <"yes — follow AGENTS.md Part 2, Tasks marked [GPU]" — or "no">
When done, open a PR and reply with the handoff block from AGENTS.md Part 4.
```

### Reviewer prompt template (Orchestrator fills this in)

```
PASTE TO: REVIEWER · <ID>
ROLE: Reviewer
TASK: <ID> — <title>
PR: <link or number>   BRANCH: task/<ID>-<slug>
ROUND: <n>
READ: CLAUDE.md (Reviewer section), AGENTS.md, SPEC.md Parts A–C and task <ID> in Part D.
BUILDER SUMMARY: <the Builder's handoff, pasted>
GPU REPORT: <the owner's self-test report, pasted — or "not applicable" / "pending">
FOCUS: <areas to check closely — defaults, catalog entries, licenses, earlier findings, etc.>
Reply with the Reviewer verdict block.
```

### Fix prompt template (Orchestrator fills this in)

```
PASTE TO: BUILDER · <ID>
ROLE: Builder
TASK: <ID> — <title>   BRANCH: task/<ID>-<slug>   ROUND: <n>
FIX THESE FINDINGS: <list by ID, with the Orchestrator's decision where it differs from the Reviewer's suggestion>
DEFERRED / NOT FIXING: <list by ID with the reason — or "none">
RECORD FROM GPU REPORT: <approved thresholds and measured VRAM/RTF to record — or "none">
Re-load the Ponytail skill, push to the same branch, and reply with the handoff block from AGENTS.md Part 4.
```

---

## Role 2 — Reviewer

**Purpose:** check the Builder's PR against the task, the spec and the project rules, and report problems. The Reviewer **does not change code** and doesn't push to the branch, so building and checking stay separate.

### How to review
1. Read `AGENTS.md` (Part 1 and Part 3 at least), `SPEC.md` Parts A–C, the task in Part D, and the Builder summary, GPU report and FOCUS in the prompt.
2. Check out the PR branch and run the task's tests plus lint, format and type checks yourself, and the catalog validator if the catalog changed. Don't trust the summary without running them. (You can't run GPU checks; rely on the owner's report for those.)
   Optionally, load the `ponytail-review` skill and use its bug, risk, load, missing-test, speed and lean checks as an extra lens on the diff. It's recommended for larger PRs. Report what it finds **in the verdict format below**, not in its own format: map its "Must fix" to Blocker or Major, "Should fix" to Major or Minor, and "Nice to have" to Nit.
3. Check, at minimum:
   - **Acceptance criteria:** each one actually met and demonstrated. For [GPU] tasks: the report covers every checkpoint the task adds, and every row passes.
   - **Scope:** nothing outside the task; no unrelated refactors.
   - **Model and text integrity (`AGENTS.md` rule 4):** nothing reimplemented that the model's package already does; warnings surfaced, not swallowed; defaults match SPEC C1 (or are approved and documented in `docs/defaults.md`); seeds fixed in tests; **golden values, thresholds and checksums not edited to make tests pass.**
   - **Catalog changes:** every file pinned to an upstream revision with size and SHA-256; formats allowed by D13 (pickle only with `weights_only=True` and an approved exception); `license.commercial` matches the allowlist; non-commercial entries have a license URL and acknowledgement text; at most 5 active models; a `catalog/CHANGELOG.md` line; a model card in `docs/models/`; measured VRAM/RTF numbers match the GPU report and none are invented.
   - **Licenses:** new dependencies justified and compatible (no GPL/AGPL in-process; GPL tools only as separate executables where the spec allows); non-commercial models and their code never bundled or vendored; watermarks untouched; the cloning consent check intact.
   - **Tests:** meaningful (they would fail if the code were wrong), not just present. Adapter tasks run the shared contract suite, not a private copy.
   - **Rules:** no secrets committed (the repo is public), including in notebooks; notebook outputs cleared; no stdout pollution in the core or workers; OS-neutral paths; generated files (types, catalog schema, lockfiles) not hand-edited; `CLEANUP.md` updated for any global install.
   - **Ponytail:** the change is the smallest complete one (no speculative abstractions, options or dependencies), and it doesn't cut anything the spec asked for (`AGENTS.md` Part 3). Every `shortcut:` comment is listed in the handoff. One that names its limit is a decision, not a finding, unless it touches a default, an acceptance criterion, input validation, checksum verification, license acceptance or the consent check.
   - **Previous findings** (round 2+): each one actually fixed.
4. Classify every finding:
   - **Blocker:** broken behaviour, failing tests, a license problem, a rule violation, or audio-quality checks bypassed. Must be fixed before merge.
   - **Major:** acceptance criterion not met, or a real bug or risk. Should be fixed before merge.
   - **Minor:** quality issue that's fine to defer.
   - **Nit:** style or preference.

### Verdict

```
PASTE TO: ORCHESTRATOR
FROM: Reviewer · <ID> · ROUND <n>
VERDICT: APPROVED  |  CHANGES REQUESTED
CHECKS RUN: <commands and results>
GPU REPORT: <checked — all pass / issues: … / not applicable / still pending>
ACCEPTANCE CRITERIA:
  - <criterion> — met / not met (why)
FINDINGS:
  R<n>-1 [Blocker] <file:line> — <problem>. Suggested fix: <…>
  R<n>-2 [Minor]   <file:line> — <problem>. Suggested fix: <…>
NEEDS OWNER CHECK: <manual checks only the owner can do, with steps — or "none">
NOTES: <anything else the Orchestrator should know — or "none">
```

- Use **APPROVED** only if there are no blockers or majors. Minors and nits can come with an approval. For a [GPU] task whose report is still pending, review everything else and say so under GPU REPORT; the Orchestrator won't merge until the report passes.
- Number findings `R<round>-<n>` so they can be tracked across rounds.
- If the spec itself looks wrong, say so under NOTES rather than inventing a requirement.
