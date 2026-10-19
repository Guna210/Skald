# AGENTS.md — Rules for agents working on Skald

This file is for every AI agent that works in this repository: Codex, Gemini, Copilot, Cursor, Claude, or any other agent. **Agents other than Claude always work as Builders.** Claude sessions can also be Builders, and are the only ones that take the Orchestrator and Reviewer roles (described in `CLAUDE.md`). Every Builder, whatever the agent, follows this file.

- **Part 1 (project rules)** applies to everyone, Claude included.
- **Parts 2–4** describe how a Builder works. Whoever builds follows them.
- **Part 5** lists the quick commands, filled in as tooling appears.
- `SPEC.md` describes what we're building: the decisions, architecture, text and audio defaults, verification plan and the task list (Part D).

If this file and `SPEC.md` disagree about *what* to build, `SPEC.md` wins. If they disagree about how agents behave or how work flows, this file wins (and `CLAUDE.md` for the Orchestrator and Reviewer roles).

---

## Part 1 — Project rules (everyone)

1. **Scope.** Implement only the task you were given. Don't refactor unrelated code. If you discover necessary work outside the task, write it down in your handoff.
2. **No global installs.** Never use `npm install -g`, `pip install --user`, system package managers, or anything that writes outside the project folder, without asking. If the owner approves, add the item to `CLEANUP.md` with its exact removal command.
3. **Keep caches in the project.** Run `scripts/dev-env.ps1` (Windows) or `source scripts/dev-env.sh` (Linux) before installing anything, once those scripts exist (task T00.2). Dev models, packs and voices live under `.cache/devdata/`, never in your real user folders.
4. **Model and text integrity.**
   - Never reimplement a model, vocoder, tokenizer or G2P (pronunciation) step. Call the model's own package (SPEC D2).
   - Never silence warnings from model packages or ffmpeg; surface them in logs and in the render quality checks.
   - Never edit golden values, intelligibility thresholds (`selftest/thresholds.json`), catalog checksums or expected outputs to make tests pass. Stop and report instead.
   - Never add a model file to the catalog without its upstream revision and file SHA-256. Never load pickle checkpoints (`.pt`, `.pth`, `.bin`) without `torch.load(..., weights_only=True)`, and never use `trust_remote_code` (SPEC D13).
   - Never strip or bypass model watermarks (SPEC D15). Never weaken the voice-cloning consent check.
   - Never bundle, vendor or redistribute a non-commercial model or its inference code; the user's machine downloads it after the user accepts its license (SPEC D10).
   - Any new text or audio default goes into `docs/defaults.md` with a rationale, and needs approval from the Orchestrator.
   - Tests that involve randomness fix the seed.
5. **Tests are part of the task.** A task is done only when its acceptance criteria pass and `pytest` / `npm test` / lint / type checks are green for the parts you touched.
6. **Schemas are the contract.** Core and worker request/response shapes live in Pydantic models. Regenerate the TypeScript types after changing them (`npm run gen:types`). Never hand-edit generated files: `app/src/shared/` types, `catalog/catalog.schema.json`, and pack lockfiles under `packs/*/locks/` (regenerate them with `scripts/make_locks.py`).
7. **stdout is sacred** in the core and in workers: only JSON-RPC messages go to stdout. Logs go to stderr or the log file.
8. **OS-neutral code.** No hard-coded path separators, shell-specific commands, or Windows-only APIs outside clearly isolated helpers. Use `pathlib` in Python and `path` in Node.
9. **Dependencies.** Add a new dependency only if the task says so or you explain why in your handoff. Check its license: no GPL or AGPL code imported or linked into our processes, and nothing whose license forbids redistribution (SPEC D10). A GPL tool may only ever be called as a separate executable, and only when the spec says so.
10. **Ponytail.** Builders follow the Ponytail skill (Part 3). The spec always takes precedence over the skill.
11. **Ask when unsure.** If the spec is ambiguous, contradicts itself, or a license reads differently from what the spec assumes, stop and ask rather than guess.
12. **Finish cleanly.** Tick the task in the `SPEC.md` Part D index, and report what changed, how you tested it, and any open questions.
13. **No secrets in the repo.** The repository is public. Never commit API keys, tokens (including Hugging Face tokens), passwords or personal data — in code, config, test fixtures, logs, notebooks, notebook outputs or commit messages. If a task seems to need a secret, stop and ask.

---

## Part 2 — How work flows

Agents can't talk to each other. The **owner** carries messages between sessions by copy-paste, and the **Orchestrator** (a Claude session) coordinates everything. As a Builder:

1. The owner pastes a prompt from the Orchestrator that starts with `PASTE TO: BUILDER · <task ID>`. That prompt, plus `SPEC.md`, is your assignment.
2. If you have questions, you write them in a question block (Part 4). The owner pastes it to the Orchestrator and pastes the answer back to you. **The Orchestrator's answers are binding**: it has the same authority as the owner.
3. When you finish, you open a pull request and write a handoff block. A Reviewer checks your work.
4. If changes are requested, you get a fix prompt listing findings by ID. Fix them on the same branch and hand off again. This repeats until the Reviewer approves.

### Tasks marked [GPU]

You can't run GPU checks yourself: cloud sessions and the owner's laptop have no NVIDIA GPU. For a **[GPU]** task:

- Make everything that can run without a GPU pass (CPU tests, the contract suite against the fake adapter, catalog validation).
- Make sure the self-test notebook (`selftest/selftest.ipynb`, SPEC C3.6) can run your work: your pack lockfiles, catalog entry and thresholds placeholders are in the branch.
- In your handoff, mark the GPU acceptance criteria as **needs owner GPU self-test**, and list the model ids to put in the notebook's `MODELS` cell.
- The owner runs the notebook on your branch and pastes back the report. If thresholds still need recording (first run of a model), you then record them per SPEC C3.5 in a fix round. Never invent VRAM, speed or threshold numbers.

### Message format

Anything meant for another session goes in **one fenced code block** whose first line says where it goes, for example:

```
PASTE TO: ORCHESTRATOR
...
```

Text outside the block is for the owner: keep it short and plain. Never split one message across several blocks.

### Git conventions

- One task = one branch = one pull request (PR).
- Branch: `task/<ID>-<short-slug>`, for example `task/T00.1-repo-scaffolding`. Use the exact name in the Orchestrator's prompt.
- PR title: `<ID>: <task title>`, for example `T00.1: Repository scaffolding`.
- Branch from the latest `main`. Never push to `main` directly. Never merge your own PR.
- Fix rounds push new commits to the same branch and PR.
- Never touch the `orchestrator` branch. It holds the Orchestrator's notes only.
- Never commit notebook outputs: clear all outputs in `selftest/selftest.ipynb` before committing.

---

## Part 3 — The Ponytail skill (Builders)

The repository includes the **Ponytail** skill at `.agents/skills/ponytail/SKILL.md` (from [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail), MIT, pinned to commit `84740e3d344b69b4a133201fa519eb37a62a2b2a`). It pushes you to write the smallest change that fully solves the task: reuse what exists, prefer the standard library and installed dependencies, and add no speculative abstractions, options or "for later" code.

**Loading it:**
- **Codex** finds it automatically in `.agents/skills/`. Invoke it explicitly at the start with `$ponytail` to be sure.
- **Any other agent, including Claude** (Claude Code doesn't scan `.agents/skills/`): open `.agents/skills/ponytail/SKILL.md`, read it in full at the start of the task, and follow it.
- Load it again after any context compaction or reset.
- Use the default level, **full**. Never use **ultra**: it questions requirements. If a requirement looks unjustified, ask the Orchestrator instead.
- The skill arrives with task T00.1. If it isn't in the repo yet, skip this part.

**Precedence: Ponytail decides *how* to build; `SPEC.md` decides *what* to build.** Everything in the task's Do, Acceptance and Tests, the decisions (SPEC A5), the text and audio defaults (SPEC C1), the verification rules (SPEC C3), this file, and the handoff format counts as "asked for", so Ponytail never cuts it. In particular:
- Write **every** test the task lists — fixtures, golden tests, contract tests and intelligibility checks — even though Ponytail alone would settle for one small check.
- Never ship a reduced version and offer to expand it later. The task is the scope.
- Never put a `shortcut:` comment on a default from SPEC C1, an acceptance criterion, input validation, checksum verification, license acceptance or the cloning consent check. List every `shortcut:` comment you add in your handoff.
- Adapters wrap the model's own package with as little code as possible — that's Ponytail and SPEC D2 agreeing. But an adapter still declares every capability, parameter and limit SPEC B6 requires.
- Ponytail's "keep the reply short" rule doesn't apply to the handoff block, which is always complete.

---

## Part 4 — Builder workflow

### Start of a task
1. Read this file, `SPEC.md` Parts A–C, your task in `SPEC.md` Part D, and anything the prompt lists under EXTRA CONTEXT.
2. Check that every task in the task's **Depends on** line is ticked on `main`. If one isn't, stop and ask.
3. Create the branch named in the prompt from the latest `main`. For a fix round, check out the existing branch and pull.
4. Load the Ponytail skill (Part 3).
5. Note where you're running (cloud Linux or the owner's Windows laptop). If an acceptance check needs another environment (Windows, or a GPU), say so in your handoff rather than skipping it silently.

### Asking questions
- Ask **before** writing a lot of code when something is ambiguous, contradicts the spec, needs a decision outside the task, or when an upstream package or license doesn't behave the way the spec says.
- Put all current questions in **one** block. For each, give the options you see and your recommendation:

```
PASTE TO: ORCHESTRATOR
FROM: Builder · <ID> · QUESTION
Q1. <question>
    Options: (a) … (b) …
    My recommendation: … because …
Q2. …
Blocked until answered: <yes / no — continuing with <assumption> meanwhile>
```

- Small, reversible choices inside the task's scope don't need a question. Make the sensible choice and list it in your handoff under DECISIONS I MADE.

### While building
- Stay inside the task's scope (rule 1). Put anything else you notice under FOLLOW-UPS in the handoff.
- Commit in small logical steps with clear messages, for example `T02.2: parse EPUB spine and nav`.
- If the Orchestrator's answer tells you to record a clarification, add it to `SPEC.md` Appendix 3 (Clarifications log) in this PR.
- When you change the catalog, add a line to `catalog/CHANGELOG.md`. When you work on an adapter, update `docs/models/<id>.md`.

### Finishing
1. Run everything the task and the Definition of Done (SPEC C6) require: tests, lint, format, type checks, and `python -m skald_core.catalog.validate catalog/catalog.json` if you touched the catalog. Fix failures. Never weaken tests or edit golden values, thresholds or checksums to make them pass.
2. Tick the task in the `SPEC.md` Part D index.
3. Push the branch and open a PR to `main` using the title convention. Put the handoff content in the PR description too.
4. Reply with the handoff block:

```
PASTE TO: ORCHESTRATOR
FROM: Builder · <ID> · DONE (round <n>)
AGENT: <agent and model, e.g. Codex / GPT-x, or Claude / Sonnet>
PR: <link>   BRANCH: task/<ID>-<slug>   RAN ON: <cloud Linux / Windows laptop>
SUMMARY: <2–5 lines on what changed>
ACCEPTANCE CRITERIA:
  - <criterion> — met / not met / needs owner check (how) / needs owner GPU self-test
TESTS RUN: <commands and results>
GPU SELF-TEST NEEDED: <model ids for the notebook's MODELS cell — or "no">
DECISIONS I MADE: <list — or "none">
SHORTCUTS: <each `shortcut:` comment added, file:line and the limit it names — or "none">
SPEC CHANGES: <clarifications/decisions added — or "none">
NEW DEPENDENCIES: <name, version, license — or "none">
CATALOG CHANGES: <models/revisions added or changed, with license and commercial flag — or "none">
GLOBAL INSTALLS / CLEANUP.md CHANGES: <list — or "none">
FINDINGS ADDRESSED (fix rounds): <finding ID → what changed — or "n/a">
FOLLOW-UPS / OPEN QUESTIONS: <list — or "none">
```

### Fix rounds
- Address each finding listed in the fix prompt, by ID. If you disagree with a finding, don't silently skip it: explain in the handoff and let the Orchestrator decide.
- Push to the same branch. Don't open a new PR.

---

## Part 5 — Quick commands

Filled in by later tasks as the tooling appears.

| What | Windows (PowerShell) | Linux (bash) |
|---|---|---|
| Set up / update the dev environment | *(added by T00.2)* | *(added by T00.2)* |
| Activate project-local caches | *(added by T00.2)* | *(added by T00.2)* |
| Fetch pinned binaries (ffmpeg, uv, Python) | *(added by T00.3)* | *(added by T00.3)* |
| Run core tests | *(added by T01.1)* | *(added by T01.1)* |
| Run worker contract tests | *(added by T03.7)* | *(added by T03.7)* |
| Validate the catalog | *(added by T03.1)* | *(added by T03.1)* |
| Regenerate pack lockfiles | *(added by T03.5)* | *(added by T03.5)* |
| Run the self-test (CPU) | *(added by T04.3)* | *(added by T04.3)* |
| Run app tests | *(added by T06.1)* | *(added by T06.1)* |
| Regenerate TypeScript types | *(added by T06.3)* | *(added by T06.3)* |
