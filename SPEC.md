# Skald — Product & Engineering Specification

**Product:** Skald — a modern, free, open-source desktop app that turns e-books into audiobooks with local text-to-speech (TTS) models. Named after the Norse poets who recited sagas aloud.
**Repository:** `Skald` (on the owner's personal GitHub account).
**Spec version:** 1.0 — 16 October 2026
**Status:** Draft for owner approval. Once approved, decisions in Part A are final unless the owner changes them.

---

## How to use this document

- **Part A** — what we are building and every decision made so far.
- **Part B** — architecture, the model catalog, engine packs, the worker protocol and the data model.
- **Part C** — text and audio defaults, the verification plan (including GPU testing on Colab/Kaggle), the development environment, and the rules every agent must follow.
- **Part D** — the task breakdown. Each task is sized for one agent session with a standard (non-flagship) model and lists its dependencies, what to read, what to produce and how "done" is checked. Tasks are self-contained: an agent needs only this spec, `AGENTS.md` and the repository.

**How work flows:** there are three roles.
- The **Orchestrator** (a Claude session; see `CLAUDE.md`) plans, answers questions and writes the prompts for the other sessions.
- **Builders** can be any agent (Codex, Gemini, Claude and so on). Each implements one task on its own branch and opens a pull request (PR), following `AGENTS.md`.
- **Reviewers** (Claude sessions; see `CLAUDE.md`) check each PR and give a verdict.

The owner carries messages between sessions by copy-paste. The Orchestrator keeps its running log and current state on a separate orphan branch, `orchestrator`, that is never merged. The prompt templates in Appendix 2 also work without an Orchestrator.

`AGENTS.md` (project rules and the Builder workflow) and `CLAUDE.md` (Orchestrator and Reviewer roles) are written by the owner before T00.1. C5 summarizes the rules they must contain.

**Markers:** **[SPIKE]** — an investigation that produces a short findings document rather than product code. **[REVIEW]** — needs a sign-off by the Orchestrator or the owner before dependent tasks start. **[STRONG MODEL]** — run with the strongest model available, because it needs judgment across many files or careful reading of licenses and upstream code. **[GPU]** — acceptance needs a run of the GPU self-test notebook (C3.6) by the owner on the PR branch.

---

# Part A — Product and decisions

## A1. Problem

audiblez (MIT, ~8.7k GitHub stars) showed that people want "e-book in, audiobook out" with a modern local model. But it uses one model (Kokoro), needs Python, pip, espeak-ng and ffmpeg installed by hand, and on Windows its README walks users through creating a virtual environment. Other tools (ebook2audiobook, abogen, pdftts, epub2tts) add more engines, but none offers what Upscayl offers for image upscaling: a one-click installer, no Python, a polished desktop app and a simple model picker.

At the same time, open TTS models improved quickly in 2025–2026 and keep getting point releases. Users need help choosing a model their hardware can run, understanding its license, and installing its updates safely.

## A2. Goal

A desktop app where a reader can go from "I have an EPUB" to "I have a chaptered `.m4b` audiobook narrated in a voice I chose", with:

1. **One-click install** from GitHub Releases: no Python, conda, pip or command line.
2. **Works out of the box, offline.** Kokoro ships inside the installer, so a CPU-only laptop can render a book with no downloads.
3. **An Upscayl-style model picker.** A short, curated list of 3–5 models, each showing languages, voice features, license, download size and how well it will run on *this* computer.
4. **Safe model updates.** Point updates to installed models appear in the app and install with one click, pinned and checksummed. New model families arrive with app updates.
5. **Voice styles.** Preset voices, voices designed from a text description, cloned voices (with consent), per-voice style controls, and separate voices for narration and dialogue.
6. **Editable and resumable.** Fix text, add pronunciations, preview any paragraph, re-render only what changed, and resume a 10-hour render after a crash or reboot.
7. **Verified output.** Every model is checked automatically for intelligibility (speech → Whisper → text round trip) before it reaches users.

## A3. Users

- **Primary:** readers who want audiobooks of their DRM-free e-books (public-domain classics, self-published work, their own writing), students, and people who need audio for accessibility (dyslexia, low vision).
- **Secondary:** indie authors producing audio drafts; language learners.
- Most target users are on **Windows**, many with laptops that have no NVIDIA GPU.

## A4. MVP scope

**In scope**
- Projects stored as ordinary folders.
- Import: EPUB 2/3 (DRM-free), plain text, Markdown. Chapter detection, front/back-matter suggestions, include/skip per chapter, inline text editing.
- Model catalog of 3–5 models with hardware fit, license badges, install/remove and point updates.
- Voice library: presets, preset blending (where supported), voice design from a description, voice cloning from a local audio file, per-voice style controls, previews.
- Voice assignment: narrator voice, optional dialogue voice (quoted speech), per-chapter and per-paragraph overrides.
- Pronunciation lexicon (per project).
- Render queue with progress, ETA, pause/resume, crash-safe resume, per-chunk quality checks with automatic retry, a "needs review" list and single-chunk re-render.
- Export: `.m4b` with chapters, cover and metadata; MP3 per chapter.
- Settings, About (versions and licenses), clear error messages.
- Headless command-line interface (used for testing and for running on Colab).
- Windows installer and Linux AppImage/.deb on GitHub Releases.

**Out of scope for MVP (backlog, Part D Phase 10)**
- macOS builds.
- GPU acceleration on AMD and Intel GPUs (they use the CPU tier).
- PDF, DOCX, MOBI/AZW3 import.
- Automatic character attribution ("which character says this line").
- Word-level timestamps / read-along subtitles.
- In-app Whisper quality checking.
- Models that need vLLM, SGLang or Docker to run.
- Cloud rendering, accounts, telemetry.

## A5. Decision log

Every decision made in planning, with the reason. Agents must not reverse these without the owner's approval.

| # | Decision | Reason |
|---|---|---|
| D1 | Build a **desktop e-book-to-audiobook app** with an Upscayl-style model picker. Do not build a general TTS studio, voice-agent server or audio editor. | Clear audience and scope; audiblez proved demand; the gap is installation and model management, not synthesis. |
| D2 | **Wrap official inference packages; never reimplement models or G2P.** Adapters only call each model's own package (e.g. `kokoro-onnx`, `chatterbox-tts`, `qwen-tts`, `voxcpm`). | Reimplementations drift silently from upstream quality. Wrapping keeps updates cheap. |
| D3 | The catalog lists **at most 5 models, and at least 3 in any release**, including **non-commercial models with a clear "Personal use only" label** and a one-time license acknowledgement before download. | A curated choice beats an overwhelming list (Upscayl's lesson). The best-sounding open models are often non-commercial, and users should be able to choose them knowingly. |
| D4 | **Point updates ship through the catalog; new model families ship with app updates.** A catalog entry pins an exact upstream revision and file checksums, and names the minimum adapter version it needs. The app offers only revisions the catalog lists. | A point update can change file formats; every revision we offer has been tested. Catalog edits need no app release. |
| D5 | **Projects pin model revisions.** Updating a model never changes an in-progress book. Old revisions stay on disk until no project uses them (users can remove them). | A book rendered with two revisions can sound different between chapters. Keeping old revisions also gives free rollback. |
| D6 | Architecture: **Electron app + frozen Python core + per-family "engine packs."** The core (frozen with PyInstaller) handles books, text, rendering, ffmpeg and Kokoro. Every other model family runs in its own worker process inside its own Python environment, created on the user's machine by a **bundled `uv` + bundled python-build-standalone** from a **hash-locked lockfile**. | Model families pin conflicting PyTorch/transformers versions. Separate environments avoid conflicts; uv makes installs fast and reproducible; nothing is installed globally. Kokoro in the core gives an offline, CPU-friendly default. |
| D7 | **Every catalog model must run natively on Windows and Linux in a single Python process (PyTorch or ONNX), with no vLLM, SGLang, Docker or WSL.** Voxtral TTS (vLLM-Omni only) and Higgs Audio V3 (SGLang-Omni only) are excluded until that changes. | Windows is the primary platform; server stacks don't run there natively and are hard for non-developers to install. |
| D8 | **Launch lineup:** (1) **Kokoro-82M** via `kokoro-onnx`, bundled, CPU; (2) **Chatterbox** (Multilingual V3 and Turbo on GPU, Nano on CPU); (3) **Qwen3-TTS** (0.6B/1.7B; CustomVoice, VoiceDesign, Base); (4) **VoxCPM2**; (5) **one non-commercial model**, chosen by spike T04.7 between **Fish Audio S2 Pro** and **Breeze TTS 2**. All but (5) are Apache-2.0 or MIT. | Covers every hardware tier, every voice-style level (presets, design, cloning, style control) and 23–30 languages, with commercially usable options first. |
| D9 | **Hardware tiers in MVP: CPU, and NVIDIA CUDA.** AMD/Intel GPUs fall back to CPU. GPUs without bfloat16 (e.g. T4, Pascal, Turing) are supported via float16. Each catalog entry states minimum VRAM/RAM; figures not published upstream are **measured** by the GPU self-test before release. | CUDA is the only GPU path all chosen models support; many users have older cards. |
| D10 | **License: Apache-2.0.** No GPL/AGPL code is imported or linked into our processes. A GPL tool may be used only as a **separate executable** (subprocess), with its notice and source offer shipped; spike T03.9 decides whether espeak-ng is used this way. **Non-commercial models and their inference code are never bundled or redistributed by us:** the user's machine downloads them from upstream after the user accepts the license. | Apache-2.0 is permissive and includes a patent grant. espeak-ng is GPL-3.0; Fish Audio's code and weights are both under a research license. |
| D11 | **EPUB parsing uses the standard library (`zipfile`) plus `lxml`**, not EbookLib. | EbookLib is AGPL (D10). EPUB is a zip of XML/XHTML files with a documented structure, so reading it is a small, well-defined job. |
| D12 | **ffmpeg: LGPL static builds** (BtbN FFmpeg-Builds), run as a subprocess, pinned by SHA-256 and **mirrored to a `deps-v1` release in our own repo**, because upstream keeps only the most recent daily builds. Same mirroring for any other pinned binary whose source URL may disappear. | LGPL is compatible when used as a separate executable; AAC encoding is built in; mirroring keeps old builds reproducible. |
| D13 | **Model-file safety:** every file is pinned by revision and SHA-256. Preferred formats: safetensors, ONNX, GGUF. Pickle checkpoints (`.pt`, `.pth`, `.bin`) are loaded only with `torch.load(..., weights_only=True)`; any exception needs Orchestrator approval and a note in the model card. **No `trust_remote_code`**: all inference code comes from the packages pinned in our lockfiles. | Pickle files can run code when loaded; the catalog is a supply-chain surface. |
| D14 | **The catalog lives in the repo** (`catalog/catalog.json`) and is fetched over HTTPS from the `main` branch. Every change goes through a PR, a Reviewer, catalog CI (V5) and, for GPU models, the GPU self-test (V6). The app caches the last valid catalog and works offline with it. | One reviewed source of truth; point updates without app releases. |
| D15 | **Voice ethics:** cloning only from a **local** audio file, after the user ticks "I have the right to use this voice", which is recorded in the voice profile. Model watermarks (e.g. Chatterbox's PerTh) are **never removed**. Exported files carry an "AI-narrated" note and the model credits in their metadata. | Consent and provenance; matches upstream model terms. |
| D16 | **Designed voices are frozen into a reference clip before a book is rendered.** The user designs a voice from a description, approves a sample, and the book is then rendered by cloning from that sample. | Voice design varies between runs (VoxCPM2's README says so; Qwen recommends design-then-clone for consistent characters). An audiobook needs the same voice for hours. |
| D17 | **Verification from day one** (C3): unit tests, golden text-pipeline tests, adapter contract tests, a speech → Whisper → text intelligibility check, catalog checks, the GPU self-test and a human listening review. | Bad audio (skipped sentences, babble, wrong language) can sound fine in a 5-second demo. Tests must catch it, not listeners at hour six. |
| D18 | **GPU testing happens on Google Colab or Kaggle** with a notebook in the repo opened by an **"Open in Colab" button**. The owner runs it manually before merging GPU adapter or catalog changes and before releases. A rented GPU is used only for models that don't fit a 16 GB T4. | The owner's laptop has no NVIDIA GPU, and GitHub's free runners have none. |
| D19 | Platforms: **Windows is primary** (designed and hand-tested there). **Linux is secondary** (builds and passes automated tests). **macOS is dropped from the MVP.** Code stays OS-neutral so macOS can be added later. | Most target users are on Windows; Linux is nearly free (CI and cloud agents run Linux); the owner has no Mac or Apple developer account. |
| D20 | Distribution via **GitHub Releases**: Windows `.exe` installer (NSIS, per-user, no admin), Linux `.AppImage` and `.deb`, built only by **GitHub Actions**. Windows builds ship **unsigned** at first (the README explains SmartScreen's "More info → Run anyway"); apply to **SignPath Foundation** for free code signing once builds are automated. | One-click install for users; the laptop only runs dev mode. SignPath is free for open-source projects built from a public repo by an automated pipeline. |
| D21 | Dev environment: **project-local** Python venv + pip for the core, local `node_modules` for the app; package caches redirected into the project's `.cache/`. Only Git, Python, Node.js and an editor are installed globally, all listed in **`CLEANUP.md`** with removal commands. Agents never install anything outside the project without approval. | The development laptop has limited storage; abandoning the project should take two minutes. Agents don't remember earlier sessions, so the record must be kept as we go. |
| D22 | Repo is **public from the start**; **no secrets** (API keys, tokens, passwords) are ever committed, including on the `orchestrator` branch. MVP uses no gated models, so no Hugging Face token is needed. If one is ever needed, the user's token is stored only on their machine with Electron `safeStorage`. | Unlimited free GitHub Actions on standard runners for public repos; required for SignPath. |
| D23 | **App stack:** electron-vite + React + TypeScript, Tailwind CSS + Radix UI components, Zustand for state, TanStack Table + Virtual for large tables, electron-builder for installers, PyInstaller for the core. | Mainstream, well-documented, MIT-licensed tools that AI agents know well; nothing needs a global install or a large toolchain. Electron avoids the Rust toolchain and MSVC Build Tools that Tauri needs on Windows. |
| D24 | **Ponytail skills** from DietrichGebert/ponytail (MIT), pinned to commit `84740e3d344b69b4a133201fa519eb37a62a2b2a`: `ponytail` copied to `.agents/skills/ponytail/` (**required for Builders**), `ponytail-review` copied to `.claude/skills/ponytail-review/` (**optional for Claude Reviewers**). Skill files only; no plugin, hooks or global files. This spec always takes precedence over the skill. | Keeps agent-written code small and free of speculative abstractions. Codex discovers repository skills in `.agents/skills/`; other agents are told by `AGENTS.md` to read the file directly. |
| D25 | **Any agent can be a Builder**, Claude included; agents other than Claude are always Builders. Every Builder follows `AGENTS.md`. **The Orchestrator and Reviewers are Claude sessions**, following `CLAUDE.md`. | Uses all of the owner's agents for the bulk of the coding with one rulebook; reviews by a different model family catch mistakes the Builder's model tends to miss. |
| D26 | **Name: Skald.** A standalone project, not part of any suite. Repository `Skald`; app ID `io.github.<owner>.skald` until the project has its own domain. A quick web search (16 Oct 2026) found no TTS or audiobook app with this name; an unrelated AI-infrastructure project `skaldlabs/skald` exists on GitHub. Domain availability not yet checked. | Short, distinctive, about reading stories aloud. |

## A6. Non-functional requirements

- **Offline-first.** Everything works offline except installing models and packs, checking for updates and fetching the catalog. No telemetry, no accounts.
- **Responsiveness.** The UI never freezes; all engine work runs as background jobs with progress.
- **Resumable.** A render survives app restarts, crashes and reboots; finished chunks are never redone unless their inputs change.
- **Reproducibility.** Every render records text hashes, voice profiles, model revisions, adapter and pack versions, parameters and seeds.
- **Robust paths.** Must work with Windows paths containing spaces, non-ASCII characters and long names. External tools (ffmpeg, workers) are given files in a fresh temporary directory with short ASCII-only names where possible, and results are copied back.
- **Sleep.** While rendering, the app asks the OS not to sleep (Electron `powerSaveBlocker`) and tells the user.
- **Disk space.** Install and render steps check free space first and say what they need.
- **Install size.** Installer download under **600 MB** (includes Kokoro and ffmpeg). Engine packs and models download separately and show their sizes first.
- **Hardware floor.** Kokoro renders on a 4-core laptop with 8 GB RAM.
- **Accessibility.** Keyboard navigable, visible focus, sufficient contrast in both themes, no information conveyed by colour alone; audio controls usable without a mouse.

---

# Part B — Architecture

## B1. Overview

```
┌──────────────────────────── Electron app ────────────────────────────┐
│  Renderer (React + TS): Home, Book, Voices, Models, Render, Export,  │
│  Settings · audio player · typed RPC client (generated types)        │
│            ▲ window.skald.* (preload bridge, contextIsolation)       │
│  Main process: windows, dialogs, recent projects, powerSaveBlocker,  │
│  core process manager (JSON-RPC over stdio)                          │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ JSON-RPC 2.0, newline-delimited, stdio
┌───────────────────────────────▼──────────────────────────────────────┐
│  Core (skald_core; frozen with PyInstaller)                          │
│   rpc/ jobs/ project/ book/ text/ catalog/ hardware/ packs/ models/  │
│   workers/ voices/ render/ audio/ export/ verify/ schemas/ cli.py    │
│        │ subprocess (ffmpeg LGPL)    │ subprocess (uv)               │
│        ▼                             ▼                               │
│   ffmpeg, ffprobe            creates engine packs in user data       │
│        │                                                             │
│        │ spawns one worker per model family (JSON-RPC over stdio)    │
│        ▼                                                             │
│  ┌──────────────────────┐ ┌───────────────────────────────────────┐  │
│  │ Kokoro worker        │ │ Pack workers (one venv per family)    │  │
│  │ = core exe in        │ │ <pack>/python -m skald_worker         │  │
│  │   --worker mode      │ │   --adapter chatterbox|qwen3|voxcpm2… │  │
│  │ kokoro-onnx + ORT    │ │ PyTorch CPU or CUDA + model package   │  │
│  └──────────────────────┘ └───────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
        ▲ HTTPS (only when installing or updating)
        │ catalog.json (GitHub raw) · model files (Hugging Face, pinned
        │ revisions) · wheels (PyPI, download.pytorch.org, hash-locked)
```

## B2. Technology stack

| Layer | Choice | Notes |
|---|---|---|
| Desktop shell | Electron (latest stable at start) | `contextIsolation: true`, `sandbox: true`, `nodeIntegration: false`, strict Content-Security-Policy. |
| Build | electron-vite + Vite | |
| UI | React 18+, TypeScript strict, Tailwind + Radix (shadcn-style components copied into the repo), Zustand, TanStack Table/Virtual | |
| Core language | Python 3.12 | |
| Core deps | lxml, pydantic v2, numpy, soundfile, psutil, requests, pysbd (sentence splitting), kokoro-onnx, onnxruntime, misaki | Exact pins at T01.1 and T04.1; licenses checked there (no GPL/AGPL). |
| Worker deps | per pack: the model's own package, its pinned PyTorch, pydantic, numpy, soundfile | Lockfiles in `packs/` (B5). |
| Environment tooling (shipped) | `uv` binary + python-build-standalone CPython 3.12 | Bundled in the installer; used only to build packs. |
| Audio tool (shipped) | ffmpeg + ffprobe, LGPL static build, pinned and mirrored (D12) | Concatenation, resampling, loudness, AAC/MP3 encoding, M4B muxing. |
| Packaging | PyInstaller one-folder (core); electron-builder (app) | |
| App ↔ core, core ↔ worker | JSON-RPC 2.0 over stdio, one JSON object per line | No network ports, no firewall prompts. |
| Tests | pytest, Vitest, Playwright for Electron; faster-whisper (dev only) for intelligibility tests | Whisper is never shipped. |
| Lint/format | ruff + mypy (Python); ESLint + Prettier + `tsc --noEmit` (app) | |
| CI/CD | GitHub Actions on `windows-latest` and `ubuntu-latest` | |

## B3. Repository layout

```
Skald/
├─ AGENTS.md                       # project rules + Builder workflow (every Builder)
├─ CLAUDE.md                       # Orchestrator and Reviewer roles
├─ SPEC.md                         # this document
├─ CLEANUP.md                      # every global install + removal command
├─ README.md  CONTRIBUTING.md  LICENSE  CITATION.cff
├─ THIRD_PARTY_NOTICES.md  MODEL_LICENSES.md   # generated (T09.4)
├─ .gitignore  .editorconfig  .npmrc
├─ .agents/skills/ponytail/        # D24
├─ .claude/skills/ponytail-review/ # D24
├─ catalog/
│  ├─ catalog.json                 # the live model catalog (B4)
│  ├─ catalog.schema.json          # exported from Pydantic (do not hand-edit)
│  └─ CHANGELOG.md                 # human-readable history of catalog changes
├─ packs/<family>/
│  ├─ requirements.in              # direct dependencies of the pack
│  └─ locks/<os>-<accel>.txt       # uv-compiled with hashes (do not hand-edit)
├─ docs/
│  ├─ defaults.md                  # every text/audio default + rationale (C1)
│  ├─ models/<model_id>.md         # our model cards: license, features, measured speed/VRAM
│  ├─ spikes/                      # findings from [SPIKE] tasks
│  └─ verification/                # test reports, review checklists
├─ scripts/
│  ├─ setup.ps1 setup.sh           # create venv, install deps, set cache dirs
│  ├─ dev-env.ps1 dev-env.sh       # export cache env vars for a shell session
│  ├─ deps.lock.json               # pinned binaries: ffmpeg, uv, python-build-standalone
│  ├─ fetch_deps.py                # download + verify pinned binaries into vendor/
│  └─ make_locks.py                # regenerate pack lockfiles with uv
├─ core/
│  ├─ pyproject.toml  requirements.lock
│  ├─ skald_core/  (rpc jobs project book text catalog hardware packs models
│  │                workers voices render audio export verify schemas cli.py)
│  └─ tests/ (data/ golden/)
├─ worker/
│  ├─ pyproject.toml               # builds the skald_worker wheel installed into every pack
│  ├─ skald_worker/ (protocol.py, adapters/{fake,kokoro,chatterbox,qwen3,voxcpm2,<nc>}.py, assets/)
│  └─ tests/contract/              # the adapter contract suite (V3)
├─ selftest/
│  ├─ selftest.ipynb               # GPU self-test notebook (C3.6)
│  ├─ passages/<lang>/             # public-domain test passages
│  └─ thresholds.json              # intelligibility thresholds (C3.5)
├─ app/
│  ├─ package.json  electron.vite.config.ts  electron-builder.yml
│  └─ src/ main/ preload/ renderer/ shared/   # shared/ holds generated RPC types (do not hand-edit)
├─ vendor/                         # gitignored: ffmpeg, uv, python for dev
├─ .cache/                         # gitignored: pip/uv/npm/electron caches, dev packs and models
└─ .github/workflows/  ci.yml  catalog.yml  cpu-models.yml  release.yml
```

## B4. The model catalog

### B4.1 Rules

- **At most 5 models** with `status: "active"` at any time, and **at least 3** in any released catalog. The validator enforces both (the minimum only with `--release`, so the catalog can grow during development). Retired models may remain with `status: "retired"`: not offered for new downloads, still usable where installed.
- One catalog entry = one **model family** as users see it (e.g. "Qwen3-TTS"), containing one or more **checkpoints** (e.g. 0.6B CustomVoice, 1.7B VoiceDesign) and a list of **revisions** for each.
- Each revision pins: upstream repo, commit SHA (or release tag for GitHub release assets), every file with size and SHA-256, file format, and the **minimum adapter version** that supports it.
- The app ignores entries whose adapter it doesn't have, or whose minimum adapter or app version is newer than its own, and shows "Requires an app update" for them.
- `license.commercial` is `true` only for licenses on an allowlist (Apache-2.0, MIT, BSD, NVIDIA Open Model License). Everything else is `false` and shows **Personal use only**.
- A point update = a new revision added to an existing checkpoint, plus a `catalog/CHANGELOG.md` line. It becomes the default for **new** projects only (D5).

### B4.2 Example (abbreviated; real values are filled in by the adapter tasks)

```json
{
  "schema_version": 1,
  "min_app_version": "0.1.0",
  "updated_at": "2026-10-16",
  "models": [
    {
      "id": "kokoro",
      "name": "Kokoro",
      "status": "active",
      "family_adapter": "kokoro",
      "pack": null,
      "summary": "Small, fast and natural. Runs on any computer.",
      "license": { "name": "Apache-2.0", "url": "https://huggingface.co/hexgrad/Kokoro-82M", "commercial": true },
      "languages": ["en-us", "en-gb", "es", "fr", "hi", "it", "ja", "pt-br", "zh"],
      "capabilities": ["presets", "blend", "speed"],
      "hardware": { "cpu": { "min_ram_gb": 4, "rtf_reference": null }, "cuda": null },
      "notes": { "watermark": null },
      "checkpoints": [
        {
          "id": "kokoro-v1.0",
          "max_chars": 400,
          "default_revision": "r1",
          "revisions": [
            {
              "id": "r1",
              "bundled": true,
              "min_adapter_version": "1.0.0",
              "source": { "host": "github-release", "repo": "thewh1teagle/kokoro-onnx", "ref": "model-files-v1.1" },
              "files": [
                { "path": "kokoro-v1.0.onnx", "format": "onnx", "size": 0, "sha256": "…" },
                { "path": "voices-v1.0.bin", "format": "npz", "size": 0, "sha256": "…" }
              ],
              "changelog": "Initial release."
            }
          ]
        }
      ]
    }
  ]
}
```

Pydantic models in `skald_core/catalog/schema.py` are the source of truth; `catalog.schema.json` is exported from them.

### B4.3 Fit rating

The core combines the probed hardware (B7) with each checkpoint's `hardware` block and shows one of: **Great** (comfortably above minimums, measured RTF ≤ 0.5), **Good** (meets minimums), **Slow** (runs on CPU but RTF > 1, i.e. slower than real time), **Not supported** (with the reason, e.g. "needs an NVIDIA GPU with 8 GB"). The estimate "about N hours for this book" uses the measured RTF for the user's tier and the book's character count, labelled as an estimate.

## B5. Engine packs

- A **pack** is a Python environment for one model family and one accelerator: `<family>-<os>-<accel>`, where `accel` is `cpu` or `cu12` (the exact CUDA minor version is chosen per lockfile).
- **Inputs (in the repo):** `packs/<family>/requirements.in` and lockfiles generated by `scripts/make_locks.py` (`uv pip compile --generate-hashes`, with the PyTorch index URL pinned for CUDA builds). Lockfiles are never hand-edited.
- **Installation on the user's machine, done by the core:**
  1. Create `<userData>/packs/<family>-<os>-<accel>-<lockhash8>/` with the bundled `uv` and the bundled CPython 3.12 (`uv venv --python <bundled python>`). A pack may declare another Python version; then uv downloads it (spike T03.4 confirms how).
  2. `uv pip sync --require-hashes <lockfile>` with `UV_CACHE_DIR=<userData>/uv-cache` and hard-link mode, so identical wheels (e.g. the same PyTorch) are stored once across packs.
  3. Install the bundled `skald_worker` wheel (no network).
  4. Run `python -m skald_worker --adapter <family> --check`; it must report the adapter version and detected device.
  5. Write `pack.json` (lockfile hash, worker version, uv version, Python version, created time). A pack is valid only if `pack.json` exists; half-built packs are deleted and rebuilt.
- **Repair** rebuilds a pack from its lockfile. **Remove** deletes it and runs `uv cache prune`.
- Network hosts used: PyPI, `download.pytorch.org`, and GitHub (for uv's Python downloads if needed). Errors map to clear kinds (`offline`, `pack_install_failed` with the last 30 log lines).
- Kokoro has no pack: it runs inside the frozen core (`--worker kokoro`).

## B6. Worker protocol

Workers speak JSON-RPC 2.0 over stdio with the same rules as the core (B8: nothing but JSON on stdout). By default the core runs **one model worker at a time** (VRAM), keeps it loaded between chunks, and restarts it once after a crash.

| Method | Purpose |
|---|---|
| `worker.hello` | → `{ adapter, adapter_version, worker_version, python, torch?, device_options: ["cpu","cuda:0",…], capabilities }` |
| `worker.load` | `{ checkpoint_id, files_dir, device, dtype?, threads? }` → loads the model; reports peak memory after load. dtype `auto` = bfloat16 where supported, else float16 on CUDA, float32 on CPU. |
| `worker.voices` | → preset voices for the loaded checkpoint (id, display name, language, gender if given upstream) |
| `worker.synthesize` | `{ text, language, voice: VoiceSpec, params, seed, out_path }` → writes a mono WAV at the model's native rate; returns `{ sample_rate, duration_s, rtf, peak_vram_mb? }` |
| `worker.design_sample` | `{ description, sample_text, language, seed, out_path }` (design-capable adapters only) |
| `worker.unload` / `worker.shutdown` | Free memory / exit. |

`VoiceSpec` is one of `{ kind: "preset", id }`, `{ kind: "blend", parts: [{id, weight}] }`, `{ kind: "clone", reference_wav, reference_text? }`, plus an optional `style` object validated against the adapter's declared parameter schema (e.g. Chatterbox `exaggeration`, `cfg_weight`; Qwen `instruct`).

Every adapter declares: capabilities, parameter schema with defaults and ranges, `max_chars`, supported languages, and whether output is deterministic for a fixed seed on CPU.

## B7. Hardware probe

`system.hardware` returns: OS, CPU model, physical/logical cores, total and free RAM, free disk on the data drive, and NVIDIA GPUs from `nvidia-smi --query-gpu=name,memory.total,driver_version,compute_cap --format=csv,noheader` (absent → empty list). `compute_cap ≥ 8.0` → bfloat16 capable. Packs declare a minimum driver version for their CUDA build; the fit rating uses it. Non-NVIDIA GPUs are not probed in MVP; the app says "GPU acceleration currently needs an NVIDIA graphics card."

## B8. Core RPC protocol and methods

- **Transport:** the core reads requests from **stdin** and writes responses and notifications to **stdout**, one UTF-8 JSON object per line. **Nothing else may be printed to stdout**; logs go to a file and to stderr.
- **Messages** follow JSON-RPC 2.0: requests have `id`, `method`, `params`; responses have `id` and `result` or `error`; notifications have `method` and `params` and no `id`.
- **Long operations** return immediately with `{ "job_id": "..." }` and report through notifications:
  - `job.progress` → `{ job_id, fraction (0–1 or null), message, stage }`
  - `job.log` → `{ job_id, level, message }`
  - `job.finished` → `{ job_id, status: "succeeded"|"failed"|"cancelled", result?, error? }`
- **Error object:** `{ code, message, data: { kind, details, hint } }`. `kind` is a stable machine-readable string the UI maps to friendly messages: `offline`, `epub_drm`, `epub_invalid`, `unsupported_format`, `pack_install_failed`, `model_download_failed`, `checksum_mismatch`, `worker_crashed`, `out_of_memory`, `not_enough_disk`, `license_not_accepted`, `adapter_unavailable`, `ffmpeg_failed`, `folder_not_empty`, `internal`.
- **Schemas:** all request/response shapes are Pydantic models in `skald_core/schemas/`. A script exports them as JSON Schema; the app generates TypeScript types from that (T06.3). The schemas are the single source of truth.

| Method | Kind | Purpose |
|---|---|---|
| `system.info` / `system.hardware` / `system.shutdown` | sync | Versions; B7; graceful exit. |
| `catalog.get` / `catalog.refresh` | sync / job | Current catalog with compatibility and fit annotations; fetch the latest. |
| `models.list_installed` | sync | Installed checkpoints/revisions, sizes, which projects use them. |
| `models.install` / `models.update` / `models.remove` | job | Pack (if needed) + files; a new revision; delete (refused while a project pins it unless forced). |
| `license.accept` | sync | Record acceptance for a non-commercial model (stored in user settings with date and license URL). |
| `project.create` / `project.open` / `project.save` | sync | Project folder I/O. |
| `book.import` | job | EPUB/TXT/MD → book model. |
| `book.get` / `book.update` | sync | Chapters, paragraphs, include/skip, text edits, language. |
| `lexicon.get` / `lexicon.set` | sync | Pronunciation rules. |
| `voices.list` / `voices.create` / `voices.delete` | sync | Voice library. |
| `voices.preview` | job | Render a sample sentence with a voice. |
| `voices.design` | job | Design candidates from a description (D16). |
| `assign.get` / `assign.set` | sync | Narrator/dialogue/override assignments. |
| `render.plan` | sync | Chunk counts, cached vs to do, time estimate. |
| `render.start` / `render.pause` / `render.resume` / `render.status` | job / sync | Render queue. |
| `render.chunks` / `render.rerender` | sync / job | Chunk list with status; re-render one chunk (optionally with a new seed). |
| `export.m4b` / `export.mp3` | job | Final files. |
| `job.cancel` / `job.pause` / `job.resume` / `job.status` | sync | Job control and polling. |

## B9. Project folder and user data

```
MyBook/                                  # project folder chosen by the user
├─ skald-project.json                    # manifest: schema_version, name, ids, base seed, timestamps
├─ source/original.epub                  # copied input
├─ book.json                             # chapters → paragraphs → sentences, with stable ids
├─ lexicon.json                          # pronunciation rules
├─ assignments.json                      # narrator, dialogue, overrides
├─ voices.lock.json                      # voice profiles used, frozen copies (D5, D16)
├─ models.lock.json                      # model/checkpoint/revision/adapter pinned by this project
├─ cache/chunks/<sha256>.flac            # content-addressed rendered chunks
└─ renders/<render_id>/
   ├─ render.json                        # reproducibility record (C1.5)
   ├─ chapters/<nn>.flac   qc.json
   └─ exports/…
```

```
<userData>/                              # Electron userData folder (per user, no admin)
├─ settings.json  recent.json  licenses.json
├─ catalog.cache.json
├─ models/<model_id>/<checkpoint_id>/<revision_id>/…   # verified files + .complete marker
├─ packs/<pack_dir>/   uv-cache/
├─ voices/<voice_id>/voice.json  reference.wav
└─ logs/
```

Settings may move `models/`, `packs/` and `uv-cache/` to another drive (one setting: "Model storage folder").

**Chunk cache key** = SHA-256 of: normalized text after the lexicon (C1.2), language, model id, checkpoint id, revision id, adapter version, voice spec (including the reference clip's hash), style params, seed. Changing any input re-renders only the affected chunks.

**Rules:** all writes are atomic (write to a temp file in the same folder, then `os.replace`); IDs are short random strings with prefixes (`v_` voice, `rn_` render, `ch_` chapter, `p_` paragraph) plus 8 lowercase alphanumerics, except paragraph/chunk ids that must be stable (B9 cache key, T02.3); all stored paths are relative to the project root; the manifest has a `schema_version` integer and a migration hook.

## B10. UI structure

- **Home:** New audiobook (pick an EPUB/TXT/MD file and a project folder), Open, Recent, "Try a sample" (a bundled short public-domain story).
- **Workspace steps (left):** Book → Voices → Render → Export, plus **Models**, always reachable from the top bar (like Upscayl's model selector). Steps are a guide, not a cage; each shows its status (not started / ready / needs attention / done).
- **Book:** chapter list with include/skip toggles and suggested skips (cover, copyright, index), paragraph view with inline edit, language selector, play-from-here preview.
- **Voices:** library of voice cards with play buttons; tabs "Presets", "Design", "Clone"; style sliders; assignment panel (narrator, dialogue, overrides).
- **Models:** cards in a grid: name, one-line summary, **license badge** (Commercial OK / Personal use only), languages, capability chips (Presets · Design · Clone · Style), download size, **fit rating for this PC**, Install / Update / Remove, and an update badge with the changelog line.
- **Render:** overall progress, ETA, current chapter/paragraph, pause/resume, chunk table (virtualized) with status and a "needs review" filter, play and re-render per chunk.
- **Export:** M4B (cover, title, author, narrator credit), MP3 per chapter, destination.
- **Jobs drawer** (bottom, collapsible) for installs, imports and renders. Light and dark themes, following the OS by default.

---

# Part C — Defaults, verification, environment, agent rules

## C1. Text and audio defaults

Every default here is also written into `docs/defaults.md` with its rationale (T00.1 creates the file; tasks that implement a default update it). Changing a default needs Orchestrator approval.

### C1.1 Import (EPUB)

1. Refuse DRM-protected books: `META-INF/encryption.xml` listing anything other than font obfuscation → `epub_drm` with a plain explanation. Never attempt to remove DRM.
2. Reading order = OPF spine (`linear="no"` items excluded by default; the user can include them). Chapter titles from the EPUB 3 navigation document, else the NCX, else the first heading, else "Chapter N".
3. Each spine item is a chapter by default; a navigation entry pointing inside a file splits it at that anchor.
4. **Suggested skips** (unticked by default, the user can re-tick): items marked by `epub:type` or landmarks as cover, toc, copyright-page or index, and items with fewer than 200 characters of text.
5. Text extraction from XHTML: block elements → paragraphs; headings kept as their own paragraph; `<br>` → line break inside a paragraph; images skipped (alt text not read by default); tables read row by row; **footnotes/endnotes** (`epub:type="noteref"`/`"footnote"`/`"endnote"`, `role="doc-noteref"`) → note references removed, note bodies skipped by default.
6. Metadata: title, author(s), language (`dc:language`), cover image (EPUB 3 `cover-image` property or EPUB 2 `meta name="cover"`).
7. XML parsing with lxml **without** network access, DTD loading or entity resolution (`resolve_entities=False`, `no_network=True`, `load_dtd=False`).

### C1.2 Text preparation

1. Unicode **NFC**; remove soft hyphens and zero-width characters; collapse whitespace; keep quotation marks and dashes as written.
2. **Lexicon** (per project): whole-word, case-insensitive by default, replacement text (a respelling). Applied before chunking, longest match first. Each rule shows how many times it matched. The display text is never changed.
3. **Number and abbreviation normalization** is left to each model (most handle it). An adapter may declare that its model needs pre-normalization; then the adapter (not the core) does it with the model's own recommended tool.
4. **Sentence splitting:** pysbd for the book's language; for languages pysbd doesn't support, split at sentence-ending punctuation.
5. **Chunking:** whole sentences packed up to the checkpoint's `max_chars`; a sentence longer than `max_chars` is split at `;`, `:`, `,` or spaces, in that order. Chunks never cross paragraph boundaries.
6. **Dialogue detection** (for the dialogue voice): text inside the book language's quotation marks (`“…”`, `"…"`, `«…»`, `„…“`, `「…」`) when the quote spans at least 2 words. If quotes are unbalanced in a paragraph, the whole paragraph uses the narrator voice and is flagged.

### C1.3 Synthesis

- **Seed:** each project gets a random base seed at creation (recorded); chunk seed = hash(base seed, chunk id). Tests always fix the base seed.
- **Device:** the best available tier for the checkpoint (CUDA if supported and it fits, else CPU). The user can force CPU.
- **dtype:** `auto` (B6).
- **CPU threads:** all physical cores (Settings can lower it).
- **Speed:** 1.0 (range 0.5–2.0, only for adapters that support it).

### C1.4 Per-chunk quality checks (in the app)

| Check | Default | On failure |
|---|---|---|
| Duration vs expected (expected = characters ÷ the voice's measured characters per second, calibrated from its preview) | ratio within **0.5–2.0** | Retry once with a new seed; still failing → "needs review". |
| Internal silence | no silence **longer than 2.0 s** (below −50 dBFS) | Same. |
| Clipping | **under 0.1 %** of samples at full scale | Same. |
| Empty or NaN audio | none | Same. |

### C1.5 Assembly and export

- **Pauses:** 250 ms between chunks within a paragraph, 600 ms between paragraphs, 1,500 ms after a chapter title, 2,000 ms at the end of a chapter.
- **Resampling:** all chunks to **44.1 kHz mono** (ffmpeg's `soxr` resampler if the LGPL build includes it, else ffmpeg's default; T05.6 checks).
- **Loudness:** two-pass EBU R128 `loudnorm` per chapter to **−18 LUFS integrated, −3 dBTP true peak** (inside the common audiobook guideline of −23 to −18 dB RMS with peaks at −3 dB).
- **M4B:** AAC-LC **64 kbit/s mono**, chapter markers from included chapters, cover art, title/author/album tags, narrator tag = voice name(s), comment = "AI-narrated with <model> (<license>)", plus "Personal use only" when any non-commercial model was used.
- **MP3 per chapter:** 96 kbit/s mono, ID3 tags as above.
- **`render.json`** records: render id, timestamps, app/core/adapter/worker/pack versions, uv and Python versions, OS, hardware summary, book hash and per-chapter text hashes, lexicon hash, voices (frozen), model ids/checkpoints/revisions with file hashes, all parameters, base seed, QC summary, ffmpeg version and exact command lines.

## C2. External services

| Service | Use | Notes |
|---|---|---|
| GitHub raw (`raw.githubusercontent.com`) | `catalog/catalog.json` from `main` | Validated against the schema before use; on failure keep the cached catalog. |
| Hugging Face (`huggingface.co` and its CDN hosts) | Model files at a pinned commit: `/{repo}/resolve/{sha}/{path}` | Resumable downloads; SHA-256 verified; no token in MVP. |
| GitHub Releases | Kokoro ONNX files (kokoro-onnx releases), our `deps-v1` mirror | |
| PyPI, `download.pytorch.org` | Pack installs (hash-locked) | |

All network calls go through one small HTTP helper with timeouts, retries (max 2, with backoff), resume (HTTP Range) and the User-Agent `Skald/<version>`. Tests mock the network; a pytest marker `network` runs live checks.

## C3. Verification plan

### C3.1 Layers

| Layer | What it proves | When it runs |
|---|---|---|
| **V1 Unit tests** | Functions do what they say (parsers, chunker, lexicon, cache keys, catalog logic, fit rating). | Every commit (CI). |
| **V2 Golden text pipeline** | EPUB/TXT/MD import produces exactly the expected chapters, titles, paragraphs, skips and chunks. Expected values come from the **fixture definitions** that generated the test EPUBs (independent of the parser), plus recorded values for 2 public-domain books. | Every commit. |
| **V3 Adapter contract** | Every adapter obeys the worker protocol: hello, load, voices, synthesize (valid WAV, right rate, duration > 0), parameter validation, errors, cancel, unload. | Fake adapter and Kokoro: every commit. CPU PyTorch adapters (e.g. Chatterbox Nano): weekly and on demand (`cpu-models.yml`). GPU adapters: V6. |
| **V4 Intelligibility** | Synthesized fixed passages, transcribed back with faster-whisper, stay under word-error-rate thresholds per checkpoint and language; duration and QC checks pass. | Kokoro short passage every commit; all CPU checkpoints weekly; GPU checkpoints in V6. |
| **V5 Catalog integrity** | Schema valid; at most 5 active models (at least 3 for a release); every referenced adapter exists with a high enough version; licenses present and `commercial` matches the allowlist; every file URL reachable (network); sizes and SHA-256 match for changed entries (network); every active model has a model card in `docs/models/`. | Every PR touching `catalog/` (`catalog.yml`), and weekly. |
| **V6 GPU self-test** | GPU models install from the real catalog, load, synthesize, pass V4 thresholds, and report RTF and peak VRAM on a T4 (or a rented GPU). | Manually (owner) before merging any GPU adapter or GPU-model catalog change, and before every release. |
| **V7 Human listening review** | A person listens to the review set per model: pronunciation, pacing, artifacts, voice consistency across chapters, dialogue voice switching. | Before every release. |

**Release gate:** V1–V5 green; a V6 report for every active GPU checkpoint with all thresholds met; V7 checklist signed off.

### C3.2 Fixtures

- `core/tests/data/epub/` — **synthetic EPUBs generated by `core/tests/data/make_epubs.py`** from YAML definitions (chapters, EPUB 3 nav vs NCX-only, nested sections, footnotes, cover, copyright page, `linear="no"`, DRM-marked, malformed XML, non-ASCII file names). The YAML is the expected result; the generator writes EPUBs with the standard library only, independent of our parser.
- Two short **public-domain** EPUBs (e.g. from Project Gutenberg, license header intact), confirmed public domain and redistributable by the task that adds them.
- `selftest/passages/<lang>/` — short public-domain passages per supported language (about 400–600 characters each), including numbers, abbreviations, dialogue and a long sentence.

### C3.3 Golden files

`core/tests/golden/` stores recorded values only where no independent source defines the right answer. **Agents must never edit golden values, thresholds or expected outputs to make a test pass.** If one seems wrong, stop and report.

### C3.4 Determinism

Exact audio equality is **not** a test criterion, except where an adapter declares CPU determinism and its tests confirm it (Kokoro on CPU is expected to qualify; T04.1 checks). GPU outputs are compared by thresholds only.

### C3.5 Intelligibility thresholds

`selftest/thresholds.json` holds, per checkpoint and language: maximum WER (or CER for Chinese, Japanese and Korean), the duration-ratio band, and the Whisper model size used. Values are set **once** from the first measured run plus a margin (T04.2 for Kokoro, each adapter task for its model), reviewed by the Orchestrator, and afterwards changed only with an explanation in the PR and Orchestrator approval. Whisper runs with a fixed model size and `temperature=0`.

### C3.6 GPU self-test (Colab / Kaggle)

- `selftest/selftest.ipynb`, opened with an **Open in Colab** badge in `CONTRIBUTING.md`, linking to `https://colab.research.google.com/github/<owner>/Skald/blob/main/selftest/selftest.ipynb`. To test a PR, open the notebook from `main` and set `BRANCH` in the first cell to the PR branch (task branch names contain `/`, which doesn't fit Colab's link format reliably). If the PR changes the notebook itself, open it via Colab's **File → Open notebook → GitHub** and pick the PR branch.
- The notebook's metadata requests a GPU runtime. Cell 1 sets `BRANCH = "main"` and `MODELS = [...]`, checks for a GPU, and if there is none stops with "Runtime → Change runtime type → T4 GPU, then Run all again."
- It clones the repo at `BRANCH`, fetches the pinned binaries, builds packs **exactly as the app does** (uv + python-build-standalone + lockfiles; it never uses Colab's preinstalled PyTorch), installs models from that branch's catalog, then runs `python -m skald_core.cli selftest --models … --report report.json`.
- **The report, per checkpoint:** install time, load time, peak VRAM, RTF, WER/CER per passage, QC results, pass/fail against thresholds, and environment (GPU, driver, CUDA, versions). Audio samples are saved and shown with players.
- **Safety rules** (stated in the notebook's first markdown cell): never mount Google Drive; no tokens or secrets in cells; clear outputs before committing the notebook; only run branches that have been reviewed.
- The same notebook works on Kaggle (only the GPU-check message differs). Measured RTF and VRAM feed `docs/models/<id>.md` and the catalog's `hardware` blocks.

## C4. Development environment

### C4.1 Global prerequisites (the only things installed outside the project)

| Tool | Version | Approx. size | Remove with |
|---|---|---|---|
| Git | latest | ~0.4 GB | Windows "Apps & features" / `apt remove git` |
| Python | **3.12.x** (python.org installer on Windows) | ~0.15 GB | Windows "Apps & features" |
| Node.js | **24.x LTS** (22.x also accepted; cloud sessions may ship 22) | ~0.1 GB | Windows "Apps & features" |
| Editor (e.g. VS Code) | any | ~0.5 GB | its uninstaller |

Agent command-line tools (Claude Code, Codex), if installed locally, are also global and must be listed in `CLEANUP.md`.

### C4.2 Project-local

- `core/.venv/` — the core's development environment (~1 GB; no PyTorch).
- `.cache/packs/` — development copies of engine packs (1–5 GB each with PyTorch; install only the ones you work on; CPU packs only on the laptop).
- `.cache/uv`, `.cache/pip`, `.cache/npm`, `.cache/electron`, `.cache/electron-builder` — set by `scripts/dev-env.*` and `.npmrc`.
- `.cache/devdata/` — stands in for the app's user-data folder in dev (models, packs, voices).
- `vendor/` — ffmpeg, uv and python-build-standalone for the current OS (from `scripts/fetch_deps.py`).
- `app/node_modules/`.

The owner's laptop (Windows, AMD Ryzen 7 5700U, no NVIDIA GPU, limited storage) runs the core, Kokoro and CPU packs only. GPU work is verified via C3.6.

### C4.3 Cloud agents

Claude Code cloud and Codex cloud run Linux containers without GPUs. They can run everything except GPU packs. Their network allowlists must permit the hosts in Appendix 4. Windows-specific behaviour is covered by Windows CI.

## C5. Rules for every agent

`AGENTS.md` Part 1 is the authoritative copy of these rules; it must contain at least:

1. **Scope.** Implement only the task given. No unrelated refactors. Note necessary outside work in the handoff.
2. **No global installs** without the owner's approval; approved ones go into `CLEANUP.md` with their removal command.
3. **Caches in the project.** Source `scripts/dev-env.*` before installing anything (once T00.2 exists).
4. **Model and text integrity.**
   - Never reimplement a model, vocoder, tokenizer or G2P; call the model's own package.
   - Never silence warnings from model packages or ffmpeg; surface them in logs and in the render QC.
   - Never edit golden values, intelligibility thresholds or expected outputs to make tests pass. Stop and report.
   - Never add a model file to the catalog without its revision and file SHA-256; never load pickle files without `weights_only=True` (D13).
   - Never strip model watermarks (D15).
   - Any new text/audio default goes into `docs/defaults.md` with a rationale and needs Orchestrator approval.
   - Tests that involve randomness fix the seed.
5. **Tests are part of the task.** Done means acceptance criteria met and tests, lint and type checks green for the parts touched.
6. **Schemas are the contract.** Regenerate TypeScript types after changing them; never hand-edit generated files (types, catalog schema, lockfiles).
7. **stdout is sacred** in the core and in workers: only JSON-RPC messages.
8. **OS-neutral code.** No hard-coded path separators or shell-specific commands outside isolated helpers; `pathlib` in Python, `path` in Node.
9. **Dependencies** only when the task says so or with a reason in the handoff. Check licenses: no GPL or AGPL in-process (D10); model-package licenses are checked per pack.
10. **Ponytail.** Builders follow the Ponytail skill; this spec takes precedence over it.
11. **Ask when unsure** rather than guess.
12. **Finish cleanly.** Tick the task in the Part D index; report what changed, how it was tested, and open questions.
13. **No secrets in the repo** — code, config, fixtures, logs, notebooks or commit messages.

The Builder workflow (branches, question and handoff formats, fix rounds) is in `AGENTS.md` Parts 2–4; the Orchestrator and Reviewer workflows are in `CLAUDE.md`.

## C6. Definition of Done (applies to every task)

- Acceptance criteria are met and demonstrated (test output, or a screenshot for UI tasks).
- New code has tests at the level the task asks for.
- Lint, format and type checks pass.
- No new files outside the documented layout (or the layout section is updated).
- New defaults documented in `docs/defaults.md`.
- Catalog changes come with a `catalog/CHANGELOG.md` line; adapter tasks update `docs/models/<id>.md`.
- **[GPU]** tasks have the owner's self-test report attached to the PR.
- The task is ticked in the index.

---

# Part D — Task breakdown

## D1. How tasks are organized

- Tasks are grouped into phases. Within a phase, follow the **Depends on** field; tasks with no dependency between them can run in parallel (e.g. the Phase 6 app shell can start after T00.4 while Phases 2–5 continue).
- **Size:** S ≈ under 300 lines changed; M ≈ 300–700. There are no L tasks; anything bigger was split.
- **Read** lists the spec sections the agent needs. **Tests** lists the minimum tests; agents may add more.
- Markers: **[SPIKE]**, **[REVIEW]**, **[STRONG MODEL]**, **[GPU]** (see "How to use this document").

### Milestones

| Milestone | Reached after | What you can do |
|---|---|---|
| **M1 — Engine renders a book** | T05.8 | Import an EPUB and render an `.m4b` with Kokoro from the command line. |
| **M2 — App renders a book** | T07.12 | Do the whole flow in the desktop app (dev mode) with any installed model. |
| **M3 — Verified** | T08.3 | Soak test, GPU self-test reports and listening review done. |
| **M4 — Released** | T09.8 | v0.1.0 installers on GitHub Releases. |

## D2. Task index

Agents tick `[x]` when a task is done.

**Phase 0 — Foundation**
- [ ] T00.1 Repository scaffolding
- [ ] T00.2 Development setup scripts with project-local caches
- [ ] T00.3 Pinned binaries (ffmpeg, uv, Python) with checksums and mirror [REVIEW]
- [ ] T00.4 CI skeleton (Windows + Linux)

**Phase 1 — Core engine**
- [ ] T01.1 Core package skeleton and dependency pins
- [ ] T01.2 JSON-RPC stdio server
- [ ] T01.3 Background job manager with pause
- [ ] T01.4 Schema models, schema export, `system.info`
- [ ] T01.5 Project folder storage
- [ ] T01.6 HTTP helper and verified downloader

**Phase 2 — Book import and text**
- [ ] T02.1 EPUB fixture generator and public-domain fixtures
- [ ] T02.2 EPUB container, spine, navigation and metadata
- [ ] T02.3 XHTML to paragraphs
- [ ] T02.4 TXT and Markdown import
- [ ] T02.5 Text normalization and pronunciation lexicon
- [ ] T02.6 Sentence splitting, chunking and dialogue detection
- [ ] T02.7 `book.*` and `lexicon.*` RPC
- [ ] T02.8 Golden text-pipeline tests [REVIEW]

**Phase 3 — Model runtime**
- [ ] T03.1 Catalog schema, validator and catalog CI
- [ ] T03.2 Catalog fetch, cache and compatibility
- [ ] T03.3 Hardware probe and fit rating
- [ ] T03.4 Engine-pack spike: uv + python-build-standalone + hash-locked PyTorch [SPIKE] [STRONG MODEL] [REVIEW]
- [ ] T03.5 Pack builder: lockfiles, install, repair, remove
- [ ] T03.6 Model file installer, revisions and license acceptance
- [ ] T03.7 Worker protocol, `skald_worker` package, fake adapter, contract suite
- [ ] T03.8 Worker manager in the core
- [ ] T03.9 Kokoro G2P and GPL spike (espeak-ng) [SPIKE] [REVIEW]

**Phase 4 — Adapters and model verification**
- [ ] T04.1 Kokoro adapter (bundled)
- [ ] T04.2 Intelligibility harness and thresholds [REVIEW]
- [ ] T04.3 Self-test command and GPU notebook
- [ ] T04.4 Chatterbox adapter [GPU]
- [ ] T04.5 Qwen3-TTS adapter [GPU] [STRONG MODEL]
- [ ] T04.6 VoxCPM2 adapter [GPU]
- [ ] T04.7 Non-commercial model spike: Fish Audio S2 Pro vs Breeze TTS 2 [SPIKE] [STRONG MODEL] [REVIEW]
- [ ] T04.8 Non-commercial model adapter [GPU]

**Phase 5 — Render pipeline (engine)**
- [ ] T05.1 Voice library: profiles, presets, cloning, previews
- [ ] T05.2 Voice design and freezing
- [ ] T05.3 Voice assignments
- [ ] T05.4 Render planner and chunk cache
- [ ] T05.5 Render executor: queue, resume, pause, quality checks
- [ ] T05.6 Chapter assembly: pauses, resampling, loudness
- [ ] T05.7 Export M4B and MP3, render record
- [ ] T05.8 Headless CLI — **Milestone M1**

**Phase 6 — App shell**
- [ ] T06.1 Electron + React + TypeScript scaffold
- [ ] T06.2 Core process manager (main process)
- [ ] T06.3 Typed RPC bridge and type generation
- [ ] T06.4 UI foundation: theme, base components, layout
- [ ] T06.5 Audio player and safe media protocol
- [ ] T06.6 End-to-end test harness

**Phase 7 — Workflow UI**
- [ ] T07.1 Home screen and projects
- [ ] T07.2 Models screen (Upscayl-style picker)
- [ ] T07.3 Model updates and retired models
- [ ] T07.4 Book view
- [ ] T07.5 Voices: library, presets, cloning
- [ ] T07.6 Voice design UI
- [ ] T07.7 Assignments and pronunciation lexicon UI
- [ ] T07.8 Render screen
- [ ] T07.9 Export dialog
- [ ] T07.10 Settings and About
- [ ] T07.11 Error handling UX
- [ ] T07.12 Full-flow end-to-end test — **Milestone M2**

**Phase 8 — Verification**
- [ ] T08.1 Long-book soak test
- [ ] T08.2 Release-candidate GPU self-test [GPU] [REVIEW]
- [ ] T08.3 Listening review checklist and first review [REVIEW] — **Milestone M3**

**Phase 9 — Packaging and release**
- [ ] T09.1 Freeze the core with PyInstaller [SPIKE] [STRONG MODEL]
- [ ] T09.2 electron-builder configuration and production paths
- [ ] T09.3 Release workflow
- [ ] T09.4 Third-party and model notices
- [ ] T09.5 Packaged-app smoke test on CI
- [ ] T09.6 README, CONTRIBUTING (with Colab button), CITATION.cff
- [ ] T09.7 SignPath code signing [REVIEW]
- [ ] T09.8 Release checklist and v0.1.0 — **Milestone M4**

---

## D3. Phase 0 — Foundation

### T00.1 Repository scaffolding
- **Depends on:** — (`AGENTS.md` and `CLAUDE.md` have been added by the owner)
- **Size:** S
- **Read:** A5, B3, C1, C4, C5, C6
- **Do:**
  1. Create the directory tree from B3 (empty folders get a `.gitkeep`).
  2. `AGENTS.md` and `CLAUDE.md` already exist. **Do not overwrite them.** Check that the paths they mention match the tree.
  3. `CLEANUP.md`: the global prerequisites table from C4.1; a section listing project-local items (`core/.venv`, `app/node_modules`, `.cache/`, `vendor/`); a note that **the installed app** keeps models, packs and voices in its user-data folder (path per OS) and how to delete them; and a "Full removal" checklist (delete the repo folder, uninstall the app and its data, then the global tools if no longer needed).
  4. `docs/defaults.md`: transcribe C1 as a list of defaults, each with a one-line rationale.
  5. `.gitignore` covering: `.venv/`, `node_modules/`, `.cache/`, `vendor/`, `dist/`, `out/`, `release/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `logs/`, `*.log`, `selftest/out/`, OS junk files, and `*.wav`, `*.flac`, `*.m4b`, `*.mp3` everywhere except `core/tests/data/` and `worker/skald_worker/assets/`.
  6. `.editorconfig` (UTF-8, LF, 2 spaces for TS/JSON/YAML, 4 for Python, final newline).
  7. `LICENSE` with the official Apache-2.0 text (from https://www.apache.org/licenses/LICENSE-2.0.txt), copyright line `Copyright 2026 Skald contributors`; `README.md` stub (one paragraph and "Under development").
  8. Vendor the Ponytail skills (D24): from https://github.com/DietrichGebert/ponytail at commit `84740e3d344b69b4a133201fa519eb37a62a2b2a`, copy `skills/ponytail/SKILL.md` to `.agents/skills/ponytail/SKILL.md` and `skills/ponytail-review/SKILL.md` to `.claude/skills/ponytail-review/SKILL.md`, unchanged. Put a copy of Ponytail's `LICENSE` in each folder and a `SOURCE.md` naming the repository, commit and date. Copy nothing else (no hooks, commands or plugin files). Once copied, load the Ponytail skill yourself for the rest of this task.
  9. `catalog/CHANGELOG.md` with a header only.
- **Acceptance:** tree matches B3; `git status` after creating `core/.venv/x`, `.cache/x` and `vendor/x` shows nothing; `AGENTS.md` and `CLAUDE.md` unchanged apart from path fixes; each Ponytail folder contains `SKILL.md` (identical to upstream), `LICENSE` and `SOURCE.md`.
- **Tests:** none (documentation task).

### T00.2 Development setup scripts with project-local caches
- **Depends on:** T00.1
- **Size:** S
- **Read:** C4, C5
- **Do:**
  1. `scripts/dev-env.ps1` and `scripts/dev-env.sh`: compute the repo root from the script's location and set `PIP_CACHE_DIR`, `UV_CACHE_DIR`, `npm_config_cache`, `ELECTRON_CACHE`, `ELECTRON_BUILDER_CACHE` to absolute paths under `<repo>/.cache/`; also `SKALD_DEV_DATA=<repo>/.cache/devdata` (the core uses it instead of the user-data folder in dev) and `SKALD_VENDOR=<repo>/vendor`.
  2. `scripts/setup.ps1` and `scripts/setup.sh`: source dev-env; check that Python 3.12.x and Node 22.x or 24.x are on PATH (print a clear message with download links and exit non-zero if not); create `core/.venv` if missing; upgrade pip inside it; if `core/pyproject.toml` exists, `pip install -e "core[dev]"`; if `worker/pyproject.toml` exists, `pip install -e worker`; if `app/package-lock.json` exists, `npm ci` in `app/`; if `scripts/deps.lock.json` exists, run `scripts/fetch_deps.py`.
  3. Scripts are idempotent and never write outside the repo.
  4. Fill in the "Set up" and "Activate caches" rows of the Quick commands table in `AGENTS.md`.
- **Acceptance:** running setup twice succeeds both times; after setup, `pip cache dir` (inside the venv, with dev-env sourced) and `npm config get cache` print paths inside `.cache/`.
- **Tests:** manual run output pasted in the handoff (bash; PowerShell too if on Windows).

### T00.3 Pinned binaries (ffmpeg, uv, Python) with checksums and mirror [REVIEW]
- **Depends on:** T00.1
- **Size:** S
- **Read:** D10, D12 in A5; B5
- **Do:**
  1. Choose one **BtbN FFmpeg-Builds LGPL static** release-branch build (latest stable `n<major>.<minor>`) for `win64` and `linux64`; the latest stable **uv** release for Windows x86-64 and Linux x86-64; the latest **python-build-standalone** CPython **3.12** `install_only_stripped` build for both platforms.
  2. Download each, compute SHA-256, and write `scripts/deps.lock.json`: `{ "<name>": { "version", "source_url", "license", "assets": { "<platform>": { "file", "url", "mirror_url", "sha256" } } } }`.
  3. Write `docs/spikes/deps-mirror.md` with step-by-step instructions for the owner to create a GitHub Release `deps-v1` in this repo and upload exactly these files. `mirror_url` points there; `fetch_deps.py` tries the mirror first, then the source.
  4. `scripts/fetch_deps.py` (standard library only): detect platform → assets; skip if already present with the right hash; otherwise download, verify SHA-256 (delete and exit 1 on mismatch), extract into `vendor/<name>/<platform>/`, mark executables on Linux; then run `ffmpeg -version`, `uv --version` and `python --version`.
- **Acceptance:** a fresh run downloads and verifies; a second run is a no-op; tampering with one byte makes the script re-download; the printed ffmpeg configuration contains neither `--enable-gpl` nor `--enable-nonfree`; the owner reviews the lock file and creates the mirror release.
- **Tests:** `scripts/tests/test_fetch_deps.py` — hash mismatch, platform selection, mirror fallback (with patched downloads and small fake files).

### T00.4 CI skeleton (Windows + Linux)
- **Depends on:** T00.2, T00.3
- **Size:** S
- **Read:** B2, C3.1, C4
- **Do:** `.github/workflows/ci.yml` triggered on every push (all branches) and on pull requests, with `concurrency` cancelling superseded runs for the same branch.
  - Job `core` (matrix `windows-latest`, `ubuntu-latest`): set up Python 3.12 with pip caching; run the setup script; `ruff check`, `ruff format --check`, `mypy`, `pytest -m "not network and not slow and not torch and not gpu"`. Skips gracefully while `core/pyproject.toml` is missing.
  - Job `worker` (same matrix): the same checks for `worker/`. Skips while `worker/pyproject.toml` is missing.
  - Job `app` (same matrix): Node 24; `npm ci`; `npm run lint`; `npm run typecheck`; `npm test`. Skips while `app/package.json` is missing.
  - Cache `.cache/uv` and `vendor/` keyed on the lockfiles.
- **Acceptance:** the workflow is green on a PR in the near-empty repo; logs show the skip messages.
- **Tests:** the workflow itself.

---

## D4. Phase 1 — Core engine

### T01.1 Core package skeleton and dependency pins
- **Depends on:** T00.2
- **Size:** S
- **Read:** B2, B3, D10–D11
- **Do:**
  1. `core/pyproject.toml`: project `skald-core`, version `0.1.0`, `requires-python = ">=3.12,<3.13"`, package `skald_core`. Runtime deps pinned with `==` to the latest versions: lxml, pydantic (v2), numpy, soundfile, psutil, requests, pysbd. (kokoro-onnx, onnxruntime and misaki are added by T04.1 after spike T03.9.) Dev extras: pytest, pytest-timeout, ruff, mypy, types-requests. **Check each license** (no GPL/AGPL) and list them in the handoff.
  2. ruff (line length 100); mypy strict for `skald_core`; pytest markers `network`, `slow`, `torch`, `gpu`.
  3. `skald_core/__init__.py` with `__version__`; `__main__.py` supporting `--version`.
  4. `tests/test_imports.py` importing every dependency.
  5. Confirm everything installs from wheels on Windows and Linux (CI). Fill in the "Run core tests" row of the Quick commands table in `AGENTS.md`.
- **Acceptance:** `python -m skald_core --version` prints `0.1.0`; CI core job green on both OSes.
- **Tests:** `test_imports.py`.

### T01.2 JSON-RPC stdio server
- **Depends on:** T01.1
- **Size:** M
- **Read:** B8, C5 rule 7
- **Do:**
  1. `rpc/server.py`: read stdin line by line; parse JSON-RPC 2.0; dispatch through a registry `register(method_name, handler, params_model, result_model)`; validate params with Pydantic; serialize results; write one JSON object per line to stdout under a lock (thread-safe), flushing after each write.
  2. Standard errors: parse error (−32700), invalid request (−32600), method not found (−32601), invalid params (−32602, with Pydantic error details), internal error (−32603). Application errors use code −32000 with `data.kind`.
  3. `SkaldError(kind, message, details=None, hint=None)` mapped to the error object.
  4. `notify(method, params)` helper for notifications.
  5. Logging to a rotating file (directory from env `SKALD_LOG_DIR`, default a temp dir) and stderr. Replace `sys.stdout` so stray `print` calls go to stderr; keep a private handle to the real stdout for the writer.
  6. `__main__.py`: with no arguments, start the server; exit cleanly on EOF or `system.shutdown`.
- **Acceptance:** a test spawns `python -m skald_core`, sends requests and gets correct responses; a handler that prints to stdout does not corrupt the stream.
- **Tests:** unit tests for dispatch and every standard error; a subprocess integration test.

### T01.3 Background job manager with pause
- **Depends on:** T01.2
- **Size:** M
- **Read:** B8 (job notifications)
- **Do:**
  1. `jobs/manager.py`: `JobManager.submit(kind, fn, **kwargs) -> job_id`, running `fn(ctx, **kwargs)` in a thread pool (max workers configurable, default 2).
  2. `JobContext`: `progress(fraction, message, stage)`, `log(level, message)`, `cancelled` property, `checkpoint()` (blocks while paused, raises `JobCancelled` when cancelled), and `register_subprocess(popen)` so cancel kills child process trees (psutil: children first, then parent).
  3. Notifications `job.progress`, `job.log`, `job.finished`; status tracking (`queued`, `running`, `paused`, `succeeded`, `failed`, `cancelled`); RPC `job.cancel`, `job.pause`, `job.resume`, `job.status`.
  4. Exceptions in jobs → `job.finished` with `failed` and a serialized error (`SkaldError` fields kept; unexpected exceptions logged with traceback and sent as kind `internal`).
  5. Progress notifications throttled to at most 10 per second per job.
- **Acceptance:** cancel stops a job running a `python -c "import time; time.sleep(60)"` subprocess within 2 s on both OSes; a paused job stops at its next checkpoint and resumes.
- **Tests:** success, failure, cancel with subprocess, pause/resume, throttling.

### T01.4 Schema models, schema export, `system.info`
- **Depends on:** T01.2
- **Size:** S
- **Read:** B6, B8, B9
- **Do:** `schemas/` Pydantic models: `Book`, `Chapter`, `Paragraph`, `Sentence`, `Chunk`, `LexiconRule`, `VoiceSpec`, `VoiceProfile`, `Assignment`, `RenderPlan`, `RenderRecord`, `ChunkStatus`, `QcResult`, `SystemInfo`, `HardwareInfo`, `JobRef`, `SkaldErrorData` (catalog models come in T03.1). snake_case fields; every model has a docstring. `python -m skald_core.schemas.export <dir>` writes one JSON Schema per model plus `index.json` (default directory `app/src/shared/schemas/`). `system.info` returns versions of the core, Python, lxml, pydantic, numpy and ffmpeg (first line of `ffmpeg -version`, from `SKALD_VENDOR` or env `SKALD_FFMPEG`).
- **Acceptance:** export writes valid JSON Schema files; `system.info` works in CI.
- **Tests:** export round trip; `system.info`.

### T01.5 Project folder storage
- **Depends on:** T01.4
- **Size:** M
- **Read:** B9
- **Do:**
  1. `project/store.py`: `create(path, name)`, `open(path)`, `save()`; manifest `skald-project.json` with `schema_version: 1`, `name`, `created_at`, `updated_at`, `base_seed` (random at creation, C1.3), and the ids of renders and voices used.
  2. ID generator per B9; atomic write helper (temp file in the same folder + `os.replace`); path helpers for every B9 file (created on demand); all stored paths relative to the project root.
  3. Migration hook `migrate(manifest) -> manifest` (no-op for v1, tested with a fake v0).
  4. RPC `project.create`, `project.open`, `project.save`.
  5. Refuse to create a project inside a non-empty folder that isn't a Skald project (`folder_not_empty`).
- **Acceptance:** create → open round-trips; paths with spaces and non-ASCII characters work.
- **Tests:** round trip; atomic write survives a simulated crash (leftover temp file ignored); non-ASCII path; migration hook.

### T01.6 HTTP helper and verified downloader
- **Depends on:** T01.1
- **Size:** S
- **Read:** C2
- **Do:** `net.py`: `get_json`, `get_text`, `download(url, dest, sha256, size, progress_cb, cancel)`. Downloads write `dest.part`, resume with HTTP Range when the server supports it, verify size and SHA-256, then rename; on mismatch delete and raise `checksum_mismatch`. Timeouts (connect 10 s, read 60 s), 2 retries with backoff on connection errors and 5xx, User-Agent `Skald/<version>`, honour `HTTPS_PROXY`. Error kinds: `offline`, `http_not_found`, `http_error`, `timeout`, `checksum_mismatch`.
- **Acceptance:** every error kind is produced in tests with a mocked transport; an interrupted download resumes.
- **Tests:** mocked responses including Range resume and checksum mismatch (no new dependencies for mocking).

---

## D5. Phase 2 — Book import and text

### T02.1 EPUB fixture generator and public-domain fixtures
- **Depends on:** T01.1
- **Size:** M
- **Read:** C1.1, C3.2
- **Do:**
  1. `core/tests/data/epub_defs/*.yaml`: each defines a book (metadata, chapters with titles and paragraphs, footnotes, cover, front matter, `linear="no"`, EPUB 2 NCX-only vs EPUB 3 nav, a chapter split by an anchor, non-ASCII file names, a DRM-marked variant, a malformed-XHTML variant).
  2. `make_epubs.py` (standard library only, **no shared code with the parser**) writes valid EPUBs (`mimetype` first, uncompressed) into `core/tests/data/epub/`. Commit the generated EPUBs, with a test that regenerating produces identical bytes.
  3. Add two short public-domain EPUBs; confirm public-domain status and redistribution terms; record sources in `core/tests/data/SOURCES.md`.
- **Acceptance:** at least 10 synthetic definitions covering every C1.1 rule; the generated files open in at least one independent EPUB reader (name it in the handoff).
- **Tests:** regeneration determinism; each EPUB is a valid zip with `mimetype` first.

### T02.2 EPUB container, spine, navigation and metadata
- **Depends on:** T02.1
- **Size:** M
- **Read:** C1.1 steps 1–4, 6–7; D11
- **Do:** `book/epub.py`: open the zip; read `META-INF/container.xml` → OPF; parse metadata, manifest, spine (with `linear`), EPUB 3 nav or NCX; resolve chapter titles and anchors; detect DRM (`epub_drm`); cover image; suggested skips. Safe XML parsing (C1.1 step 7). Zip-slip-safe path handling; refuse books over 500 MB uncompressed (`epub_invalid`).
- **Acceptance:** every synthetic fixture yields the chapter list, titles, order and skip suggestions its YAML defines.
- **Tests:** per fixture; DRM; a malicious zip path; an XML entity-expansion file is rejected safely.

### T02.3 XHTML to paragraphs
- **Depends on:** T02.2
- **Size:** M
- **Read:** C1.1 step 5
- **Do:** `book/xhtml.py`: block elements → paragraphs (headings, lists, blockquotes, tables row by row); inline elements flattened; `<br>` handling; footnote references removed and note bodies skipped; images skipped; `script`/`style` ignored. Produces `Book` (T01.4) with **stable** paragraph ids (hash of chapter id + index + text).
- **Acceptance:** paragraph text and order equal the YAML for every fixture; the public-domain books produce no empty paragraphs.
- **Tests:** per fixture; footnote cases; nested inline markup.

### T02.4 TXT and Markdown import
- **Depends on:** T02.3
- **Size:** S
- **Read:** C1.1
- **Do:** `book/text_import.py`: TXT in UTF-8, UTF-8 with BOM or UTF-16 with BOM (otherwise guess with a simple heuristic and report the guess); chapters split on lines matching `^(chapter|part|book)\b.*` (case-insensitive) or a short line preceded by 2+ blank lines; Markdown with `#`/`##` headings as chapters. Same `Book` model.
- **Acceptance:** fixtures for each case produce the expected chapters.
- **Tests:** encodings, chapter rules, Markdown headings.

### T02.5 Text normalization and pronunciation lexicon
- **Depends on:** T02.3
- **Size:** S
- **Read:** C1.2 steps 1–3
- **Do:** `text/normalize.py` (NFC, soft hyphens, zero-width characters, whitespace) and `text/lexicon.py` (C1.2 step 2 rules, match counts; produces the synthesis text and leaves the display text unchanged).
- **Acceptance:** the documented lexicon behaviour holds for overlaps, case, adjacent punctuation and non-ASCII words.
- **Tests:** table-driven.

### T02.6 Sentence splitting, chunking and dialogue detection
- **Depends on:** T02.5
- **Size:** M
- **Read:** C1.2 steps 4–6
- **Do:** `text/chunk.py`: pysbd per language with the punctuation fallback; pack sentences into chunks up to `max_chars`; split long sentences per C1.2 step 5; never cross paragraphs; mark dialogue spans (C1.2 step 6) as `narration` or `dialogue`, splitting chunks where the voice changes; flag unbalanced quotes.
- **Acceptance:** chunk boundaries for fixture passages match recorded expectations; no chunk exceeds `max_chars`; joining chunk texts reproduces the paragraph text (whitespace-normalized).
- **Tests:** long sentences, quotes in several languages, unbalanced quotes, a property test for the reconstruction rule.

### T02.7 `book.*` and `lexicon.*` RPC
- **Depends on:** T02.4, T02.6, T01.3, T01.5
- **Size:** M
- **Read:** B8, B9
- **Do:** `book.import` job (copies the source into `source/`, writes `book.json`, progress per chapter); `book.get`; `book.update` (include/skip chapters, edit paragraph text, set language), where edits mark the affected chunks stale; `lexicon.get` / `lexicon.set`.
- **Acceptance:** import → edit → reopen round-trips; an edit changes only that paragraph's chunk ids.
- **Tests:** RPC-level tests through the job manager.

### T02.8 Golden text-pipeline tests [REVIEW]
- **Depends on:** T02.7
- **Size:** S
- **Read:** C3.2, C3.3
- **Do:** `test_golden_text.py`: (a) synthetic fixtures compared against their YAML (no stored values needed); (b) for the two public-domain books, chapter titles, paragraph counts, character counts and chunk counts recorded once with `golden/make_golden_text.py`, compared automatically afterwards; (c) `docs/verification/text-review.md` listing, for those books, the first and last paragraph of every chapter, so the owner can check extraction in about 10 minutes.
- **Acceptance:** tests pass; the owner has skimmed `text-review.md`.
- **Tests:** the golden tests.

---

## D6. Phase 3 — Model runtime

### T03.1 Catalog schema, validator and catalog CI
- **Depends on:** T01.4
- **Size:** M
- **Read:** B4, C3.1 (V5), D3, D13, D14
- **Do:** `catalog/schema.py` (Pydantic, following B4.2); export `catalog/catalog.schema.json`; `python -m skald_core.catalog.validate catalog/catalog.json [--network] [--release]` checking: schema; at most 5 active models, and at least 3 with `--release`; unique ids; every `family_adapter` is in the worker's adapter registry (read from `worker/skald_worker/adapters/__init__.py`) with a version satisfying `min_adapter_version`; the license allowlist rule for `commercial`; every active model has `docs/models/<id>.md`; with `--network`, every URL is reachable and entries changed in the PR (diff against `origin/main`) are downloaded and SHA-256-checked. `.github/workflows/catalog.yml` runs it on PRs touching `catalog/` and weekly. Start `catalog/catalog.json` with `"models": []`.
- **Acceptance:** valid and invalid example catalogs behave as expected; the workflow is green.
- **Tests:** a table of invalid catalogs (6 active models, wrong `commercial` flag, missing model card, unknown adapter, bad hash with mocked network).

### T03.2 Catalog fetch, cache and compatibility
- **Depends on:** T03.1, T01.6
- **Size:** S
- **Read:** B4.1, C2
- **Do:** `catalog/client.py`: `catalog.refresh` job (fetch `https://raw.githubusercontent.com/<owner>/Skald/main/catalog/catalog.json`, URL configurable for tests and dev; validate; atomically replace `catalog.cache.json`); `catalog.get` annotates each model/checkpoint/revision with `compatible` + `reason` (adapter missing, adapter too old, app too old), `installed`, `update_available`, and fit (T03.3; a stub until then). A copy of the catalog is bundled with the app as a fallback for the first offline launch.
- **Acceptance:** the first offline launch uses the bundled copy; an invalid remote catalog keeps the cache and logs why.
- **Tests:** mocked fetch; compatibility matrix.

### T03.3 Hardware probe and fit rating
- **Depends on:** T03.1
- **Size:** S
- **Read:** B4.3, B7, D9
- **Do:** `hardware/probe.py` (`system.hardware`) and `hardware/fit.py` (B4.3 rules, time estimate from RTF and character count). A missing or failing `nvidia-smi` means no GPUs, not an error.
- **Acceptance:** fit ratings for a table of fake machines × fake checkpoints match expectations.
- **Tests:** parsing captured `nvidia-smi` outputs (several GPUs, old driver, none); the fit table.

### T03.4 Engine-pack spike [SPIKE] [STRONG MODEL] [REVIEW]
- **Depends on:** T01.1, T00.3
- **Size:** M
- **Read:** B5, D6, D9
- **Do:** Prototype B5 on Linux (cloud) and Windows (CI runner) with two sample packs: `torch-cpu` (PyTorch CPU + numpy) and `torch-cu12` (PyTorch CUDA build). Record: the lock generation command (`uv pip compile --generate-hashes` with the PyTorch index; whether Windows and Linux locks can be generated on one machine with `--python-platform`); `uv venv` with the vendored python-build-standalone; `uv pip sync --require-hashes`; hard-link deduplication across two packs on NTFS and ext4 (measure disk use); pack sizes; install time; behaviour behind `HTTPS_PROXY`; Windows long-path problems (keep pack folder names short); antivirus impact if observable; what to do when the user changes the storage folder (rebuild vs move); whether a pack needing Python 3.11 works via uv's Python downloads and where they come from; license and redistribution notes for uv and python-build-standalone. Write `docs/spikes/engine-packs.md` with the recommended commands for T03.5.
- **Acceptance:** findings document with measured numbers; Orchestrator/owner review; T03.5 adjusted if needed.
- **Tests:** throwaway scripts under `docs/spikes/scripts/`.

### T03.5 Pack builder: lockfiles, install, repair, remove
- **Depends on:** T03.4, T01.3
- **Size:** M
- **Read:** B5, `docs/spikes/engine-packs.md`
- **Do:** `scripts/make_locks.py` (regenerates `packs/*/locks/*.txt` from `requirements.in`); `packs/manager.py` implementing B5 steps 1–5 as a job with stage progress; repair; remove + `uv cache prune`; `pack.json`; a free-disk check before install (estimated size stored as a comment header in each lockfile). Create `packs/torch-cpu-smoke/` and `packs/torch-cu12-smoke/` (PyTorch plus a one-line tensor check), used only by tests and the GPU notebook.
- **Acceptance:** installing the CPU smoke pack twice is idempotent; killing an install midway leaves no valid-looking pack; repair rebuilds it.
- **Tests:** a real install of the CPU smoke pack (marker `slow`, CI weekly and on demand); unit tests with a fake `uv` executable for the failure paths.

### T03.6 Model file installer, revisions and license acceptance
- **Depends on:** T03.2, T01.6, T01.3
- **Size:** M
- **Read:** B4, B9, D3–D5, D13
- **Do:** `models/installer.py`: `models.install(model_id, checkpoint_id, revision_id?)` job → ensure the pack (T03.5) → download each file (T01.6) into `models/<…>/<revision>.part/` → verify → rename → write `.complete`; `models.update` installs a new revision and never touches project pins; `models.remove` refuses while a known project pins the revision unless `force`; `models.list_installed` with project usage (from recent projects); a cleanup offer for unpinned old revisions. `license.accept(model_id, license_url)`; installing a model with `commercial: false` without acceptance fails with `license_not_accepted`. Refuse pickle formats unless the file entry has `pickle_safe_load: true` (D13).
- **Acceptance:** install → update → remove flows work against a fake catalog with tiny files served by a local test server.
- **Tests:** checksum failure; interrupted download resume; non-commercial acceptance; refusal to remove a pinned revision.

### T03.7 Worker protocol, `skald_worker` package, fake adapter, contract suite
- **Depends on:** T01.2
- **Size:** M
- **Read:** B6, C3.1 (V3)
- **Do:** `worker/` package `skald_worker` (Python ≥ 3.11; dependencies: pydantic, numpy, soundfile only): a minimal stdio JSON-RPC loop of its own (must not import `skald_core`); an `Adapter` base class with declared capabilities, parameter schema, `max_chars`, languages and determinism flag; an adapter registry with versions; `--adapter <name> --check`. A **fake adapter** supporting every capability (writes sine-wave "speech" whose length scales with the text; can be told to fail, hang or emit silence or clipping). `worker/tests/contract/` — the reusable contract suite, parametrized by adapter name and a test-checkpoint fixture, run against the fake adapter in CI.
- **Acceptance:** the contract suite passes for the fake adapter; stdout contains only JSON-RPC in every fake failure mode.
- **Tests:** the contract suite + unit tests.

### T03.8 Worker manager in the core
- **Depends on:** T03.7, T03.5, T01.3
- **Size:** M
- **Read:** B6, D6
- **Do:** `workers/manager.py`: resolve the worker command (Kokoro → the core executable in `--worker kokoro` mode, in dev `python -m skald_worker --adapter kokoro`; pack families → `<pack>/python -m skald_worker --adapter <family>`); spawn, `hello`, `load`, keep warm, unload after idle (default 5 min), one model worker at a time (configurable), restart once after a crash and then fail with `worker_crashed`; map CUDA out-of-memory messages to `out_of_memory` with a hint (smaller checkpoint or CPU); forward worker logs into job logs.
- **Acceptance:** with the fake adapter: synthesis calls succeed, a crash mid-call restarts once, a hang is killed by timeout, cancel kills the worker.
- **Tests:** those scenarios.

### T03.9 Kokoro G2P and GPL spike [SPIKE] [REVIEW]
- **Depends on:** T01.1
- **Size:** S
- **Read:** D2, D10
- **Do:** Find out exactly how `kokoro-onnx` + `misaki` produce phonemes for each Kokoro language and where espeak-ng (GPL-3.0) is involved (English out-of-dictionary fallback; Spanish, French, Hindi, Italian and Portuguese fully; check the Japanese and Chinese extras and their licenses). Evaluate: (a) English without the espeak fallback (measure how many words fall through on the two public-domain books and what misaki does with them); (b) a fallback that calls the **espeak-ng executable** as a subprocess (no in-process loading), shipped with its license and a source offer; (c) any permissive fallback with clear provenance. Recommend per language: supported via (a), (b) or (c), or **not offered for Kokoro at launch** (other models cover it). Write `docs/spikes/kokoro-g2p.md`.
- **Acceptance:** recommendation reviewed; the outcome recorded in the clarifications log (Appendix 3).
- **Tests:** throwaway scripts.

---

## D7. Phase 4 — Adapters and model verification

Every adapter task: implements `worker/skald_worker/adapters/<name>.py`; creates `packs/<family>/requirements.in` and its lockfiles (T03.5); adds the catalog entry with every file pinned; writes `docs/models/<id>.md` (license with link, languages, capabilities, parameters and defaults, upstream recommended settings, measured speed and VRAM, known issues, watermarks); passes the contract suite (V3) and the intelligibility tests (V4) for its tier, recording its thresholds per C3.5.

### T04.1 Kokoro adapter (bundled)
- **Depends on:** T03.7, T03.9, T03.6
- **Size:** M
- **Read:** D8, B6, `docs/spikes/kokoro-g2p.md`
- **Do:** Add `kokoro-onnx`, `onnxruntime` and `misaki` (with extras per the spike) to the core. Adapter with presets (from the voices file, with languages and display names), blending (if kokoro-onnx accepts a style vector; otherwise drop the capability and say so), speed; G2P per the spike; measure a safe `max_chars`. Choose the bundled model file (full or quantized) by size and a short listening comparison; record the choice and reason. Check CPU determinism (same input twice → identical samples) and set the flag.
- **Acceptance:** contract suite passes on CPU in CI; catalog entry valid with `bundled: true`; model card written.
- **Tests:** contract suite (Kokoro); determinism test if the flag is set.

### T04.2 Intelligibility harness and thresholds [REVIEW]
- **Depends on:** T04.1
- **Size:** M
- **Read:** C3.1 (V4), C3.2, C3.5
- **Do:** Add `faster-whisper` to the core's dev extras (check its license). `skald_core/verify/intelligibility.py`: synthesize each passage in `selftest/passages/<lang>/` with a given checkpoint and voices, transcribe (fixed Whisper size per language, `temperature=0`, language forced), compute WER/CER after a small normalizer (lowercase, punctuation stripped, numbers kept as written on both sides), plus the duration ratio and QC (C1.4). Write passages for Kokoro's launch languages (public domain; sources listed). Record initial Kokoro thresholds in `selftest/thresholds.json` (first run + margin, explained in the PR). CI: the Kokoro English short passage runs on every commit (kept under 60 s, not marked `slow`); all Kokoro languages weekly in `cpu-models.yml`.
- **Acceptance:** Kokoro passes; a deliberately broken run (fake adapter emitting noise) fails; the Orchestrator approves the thresholds.
- **Tests:** harness unit tests; the Kokoro checks.

### T04.3 Self-test command and GPU notebook
- **Depends on:** T04.2, T03.8, T03.6, T03.5
- **Size:** M
- **Read:** C3.6, D18
- **Do:** `skald_core/cli.py` with a `selftest` subcommand: `--models` (ids or `all-gpu`), `--catalog <path>` (default: the repo's), `--report <path>`. It installs packs and models exactly as the app does, runs V4 per checkpoint, measures load time, RTF and peak VRAM (reported by the worker from `torch.cuda.max_memory_allocated`), and writes `report.json`, `report.md` and audio samples. `selftest/selftest.ipynb` per C3.6 (GPU runtime metadata, first-cell checks, safety rules, branch parameter; runs `fetch_deps.py` then the self-test; shows the report and audio players). Create `CONTRIBUTING.md` with a "Testing on a GPU" section containing the Open in Colab badge and the Kaggle alternative (T09.6 completes the file). Add a CI check that the committed notebook is valid JSON with all outputs cleared.
- **Acceptance:** the notebook runs end to end on a Colab T4 with Kokoro and the CUDA smoke pack from T03.5 (owner run, report attached); the same command runs locally on CPU with `--models kokoro`.
- **Tests:** CLI unit tests with the fake adapter; the notebook check.

### T04.4 Chatterbox adapter [GPU]
- **Depends on:** T04.3
- **Size:** M
- **Read:** D8, D15, B6
- **Do:** Pack `chatterbox` (`chatterbox-tts` pinned; CPU and CUDA locks). Checkpoints: **Multilingual V3** (`t3_model="v3"`, `language_id`, 23 languages; GPU), **Turbo** (English, paralinguistic tags like `[laugh]`; GPU), **Nano** (English; CPU). Capabilities: cloning from a reference clip; style parameters `exaggeration` (default 0.5) and `cfg_weight` (default 0.5) per upstream guidance. Starter voices for the clone-only checkpoints: short reference clips rendered from Kokoro presets at build time, committed with provenance in `worker/skald_worker/assets/chatterbox/`. The model card states that every output carries Resemble AI's PerTh watermark (D15).
- **Acceptance:** contract suite and V4 for Nano on CPU (`cpu-models.yml`); the owner's GPU self-test report for Multilingual V3 and Turbo, with VRAM, RTF and thresholds recorded.
- **Tests:** contract + V4.

### T04.5 Qwen3-TTS adapter [GPU] [STRONG MODEL]
- **Depends on:** T04.3
- **Size:** M
- **Read:** D8, D16, B6
- **Do:** Pack `qwen3` (`qwen-tts` pinned; CUDA lock; a CPU lock only if measured speed is usable). Checkpoints: 0.6B CustomVoice, 0.6B Base, 1.7B CustomVoice, 1.7B VoiceDesign, 1.7B Base, plus the shared `Qwen3-TTS-Tokenizer-12Hz`. Presets = the 9 CustomVoice speakers; style = `instruct` text (CustomVoice 1.7B); cloning via Base (`ref_text` when a transcript is given, otherwise `x_vector_only_mode=True`); design via VoiceDesign → `design_sample` (freezing per D16 happens in T05.2). Attention implementation `sdpa` (no flash-attn); dtype per B6; map the book language to the model's language names.
- **Acceptance:** contract + V4 in the owner's GPU self-test for every checkpoint; VRAM per checkpoint recorded in the catalog.
- **Tests:** contract + V4 (GPU); unit tests for parameter mapping.

### T04.6 VoxCPM2 adapter [GPU]
- **Depends on:** T04.3
- **Size:** M
- **Read:** D8, D16, B6
- **Do:** Pack `voxcpm2` (`voxcpm` pinned; Python 3.12; CUDA lock). Load with `load_denoiser=False`. Design = a description in parentheses at the start of the text; controllable cloning = `reference_wav_path` plus an optional parenthesized style; "ultimate" cloning when a transcript is provided (`prompt_wav_path` + `prompt_text`). Defaults `cfg_value=2.0`, `inference_timesteps=10` (upstream examples); seed passed through. Output is 48 kHz. Measure CPU speed once and record it; offer a CPU lock only if RTF < 3.
- **Acceptance:** contract + V4 in the owner's GPU self-test; upstream's ~8 GB VRAM figure confirmed or corrected in the catalog.
- **Tests:** contract + V4 (GPU).

### T04.7 Non-commercial model spike [SPIKE] [STRONG MODEL] [REVIEW]
- **Depends on:** T04.3
- **Size:** M
- **Read:** D3, D7, D10, D13
- **Do:** Compare **Fish Audio S2 Pro** and **Breeze TTS 2** (fallback candidate if both fail: XTTS v2 via the Idiap `coqui-tts` fork) on: plain-PyTorch inference in one process on Windows and Linux (no SGLang or vLLM); VRAM in float16 on a 16 GB T4 (if it doesn't fit, test on a rented 24 GB GPU and say so); Hugging Face gating; the exact license terms for weights **and** code (personal local use by end users; whether our app may download it on the user's behalf; attribution); file formats (D13); which languages actually work; stability on long passages; V4 results on the English passages; install size. Recommend one, with the catalog wording for its license badge and acknowledgement dialog. Write `docs/spikes/nc-model.md`.
- **Acceptance:** recommendation reviewed by the Orchestrator, and by the owner for the license reading.
- **Tests:** throwaway notebook or scripts.

### T04.8 Non-commercial model adapter [GPU]
- **Depends on:** T04.7, T03.6
- **Size:** M
- **Read:** `docs/spikes/nc-model.md`, D3, D10
- **Do:** Adapter; pack whose inference code is installed from upstream at a pinned version or commit on the user's machine (never vendored in our repo or installer); catalog entry with `commercial: false`, license URL and acknowledgement text; model card. Expose the model's style features (e.g. Fish's inline `[tags]`) through the parameter schema.
- **Acceptance:** contract + V4 in the owner's GPU self-test; `models.install` refuses without `license.accept`.
- **Tests:** contract + V4 (GPU).

---

## D8. Phase 5 — Render pipeline (engine)

### T05.1 Voice library: profiles, presets, cloning, previews
- **Depends on:** T03.8, T01.5, T00.3
- **Size:** M
- **Read:** B6, B9, D15
- **Do:** `voices/library.py`: `VoiceProfile` (id, name, model id, checkpoint id, `VoiceSpec`, style params, calibrated characters per second, created time, consent record for clones). `voices.list` (library + presets of installed checkpoints via `worker.voices`), `voices.create`, `voices.delete`. Clone import: local file only; ffmpeg converts to mono at the adapter's requested rate, trims leading/trailing silence, checks the length is 5–30 s (configurable per adapter) and normalizes loudness; requires `consent: true`. `voices.preview` job renders a sample sentence in the book's language, stores it, and calibrates characters per second (C1.4).
- **Acceptance:** with the fake adapter: preset, blend and clone voices can be created and previewed; a clone without consent is refused.
- **Tests:** ffmpeg conversion on fixture audio; the consent rule; calibration math.

### T05.2 Voice design and freezing
- **Depends on:** T05.1
- **Size:** S
- **Read:** D16
- **Do:** `voices.design` job: description + optional sample text → N candidates (default 3, different seeds) via `worker.design_sample`; the user picks one; `voices.create` stores `{ design_source: { description, seed, checkpoint }, spec: clone(reference = chosen sample) }`. The clone runs on the family's cloning checkpoint (Qwen Base; VoxCPM2 itself). If a family can't clone from its own design output, the adapter declares it and the UI warns that the voice may vary.
- **Acceptance:** with the fake adapter: design → pick → frozen profile; rendering the frozen profile twice with the same seed gives the same chunk cache key.
- **Tests:** flow tests.

### T05.3 Voice assignments
- **Depends on:** T05.1, T02.7
- **Size:** S
- **Read:** C1.2 step 6, B9
- **Do:** `assign.get` / `assign.set`: narrator voice (required), optional dialogue voice, per-chapter overrides, per-paragraph overrides; a resolution function giving each chunk its voice. Assignments are frozen into `voices.lock.json` when a render starts.
- **Acceptance:** precedence holds: paragraph override, then chapter override, then dialogue voice, then narrator.
- **Tests:** table-driven.

### T05.4 Render planner and chunk cache
- **Depends on:** T05.3, T03.3
- **Size:** S
- **Read:** B9 (cache key), B4.3, D5
- **Do:** `render/plan.py`: build the ordered chunk list for included chapters; compute cache keys; mark cached vs to-do; group work by model family to minimize worker swaps (output order unchanged); estimate time per tier; pin models in `models.lock.json` (D5). RPC `render.plan`.
- **Acceptance:** changing one lexicon rule marks only chunks containing that word as stale; changing one chapter's voice marks only that chapter as stale.
- **Tests:** invalidation tests; cache keys stable across runs and OSes.

### T05.5 Render executor: queue, resume, pause, quality checks
- **Depends on:** T05.4, T03.8, T01.3
- **Size:** M
- **Read:** C1.3, C1.4, A6
- **Do:** `render/execute.py`: the `render.start` job processes to-do chunks: worker synthesis → WAV → QC (C1.4) → on failure retry once with a new seed → store `cache/chunks/<key>.flac` atomically → update the chunk's status in `renders/<id>/qc.json` (atomically, after every chunk). Pause at chunk boundaries; resume from the stored status after a restart or crash; `render.chunks`; `render.rerender` (optionally with a new seed). Progress with an ETA from a moving average. Out-of-memory stops the render with a clear message instead of retrying in a loop.
- **Acceptance:** with the fake adapter: killing the core mid-render and restarting resumes without redoing finished chunks; injected silence or clipping triggers a retry, then "needs review".
- **Tests:** resume, pause, QC paths, OOM path.

### T05.6 Chapter assembly: pauses, resampling, loudness
- **Depends on:** T05.5, T00.3
- **Size:** M
- **Read:** C1.5, A6 (robust paths)
- **Do:** `audio/assemble.py`: per chapter, concatenate chunks with the C1.5 pauses (generated silence), resample to 44.1 kHz mono (check whether the LGPL build has `soxr`), run two-pass `loudnorm` to −18 LUFS / −3 dBTP, write `chapters/<nn>.flac`. All ffmpeg calls go through one wrapper that logs the exact command line, captures stderr, maps failures to `ffmpeg_failed`, and works in a fresh temporary folder with short ASCII file names.
- **Acceptance:** measured output loudness (ffmpeg `ebur128` analysis in the test) is within ±1 LU of the target; pauses are within ±20 ms of the defaults.
- **Tests:** synthetic tone chunks; loudness and timing checks.

### T05.7 Export M4B and MP3, render record
- **Depends on:** T05.6
- **Size:** M
- **Read:** C1.5, D15, B9
- **Do:** `export.m4b`: AAC 64 kbit/s mono, chapters (ffmetadata), cover, tags, AI-narration/credit/non-commercial comment; `export.mp3`: one file per chapter with ID3 tags; destination chosen by the app; `render.json` with every C1.5 field; a plain-text credits block (models, licenses, voices) for the Export and About screens.
- **Acceptance:** `ffprobe` reads back the exported M4B with the correct chapter count, titles and durations; tags present; `render.json` validates against its schema.
- **Tests:** ffprobe read-back; schema validation.

### T05.8 Headless CLI — Milestone M1
- **Depends on:** T05.7, T04.1
- **Size:** S
- **Read:** B8
- **Do:** Extend `cli.py` with `import`, `voices`, `render` and `export` subcommands working on a project folder, with `--json` output. Example: `python -m skald_core.cli render --book book.epub --project ./tmp/demo --voice kokoro:af_heart --export out.m4b`. Uses the same functions as the RPC methods (no duplicated logic).
- **Acceptance:** the example renders a public-domain fixture book end to end on CPU on both OSes; resuming after Ctrl+C works.
- **Tests:** CLI smoke test on a short fixture (`slow`).

---

## D9. Phase 6 — App shell

### T06.1 Electron + React + TypeScript scaffold
- **Depends on:** T00.4
- **Size:** M
- **Read:** B1, B2, B3, C5
- **Do:**
  1. Create `app/` with electron-vite (React + TypeScript template), TypeScript `strict`, path aliases (`@renderer`, `@shared`).
  2. Security: `contextIsolation: true`, `sandbox: true`, `nodeIntegration: false`, `webSecurity: true`; a Content-Security-Policy that allows only `self` (plus `data:`/`blob:` where needed for images and audio — document every exception); block new windows and navigation to external URLs (open external links in the OS browser via `shell.openExternal` after an allowlist check).
  3. npm scripts: `dev`, `build`, `lint` (ESLint), `format` (Prettier), `typecheck` (`tsc --noEmit` for main, preload and renderer), `test` (Vitest).
  4. A placeholder window showing "Skald" and the app version.
  5. Fill in the "Run app tests" row of the Quick commands table in `AGENTS.md`.
- **Acceptance:** `npm run dev` opens the window on Windows and Linux; lint, typecheck and test pass; CI app job green.
- **Tests:** one Vitest render test of the placeholder component.

### T06.2 Core process manager (main process)
- **Depends on:** T06.1, T01.3
- **Size:** M
- **Read:** B1, B8
- **Do:** `src/main/core.ts`:
  1. Resolve the core command: dev → `<repo>/core/.venv/(Scripts|bin)/python -m skald_core`; production → the bundled executable under `process.resourcesPath/core/` (finalized in T09.2; keep it in one function).
  2. Pass env: `SKALD_LOG_DIR` (Electron `userData/logs`), `SKALD_DATA_DIR` (userData; dev: `SKALD_DEV_DATA`), `SKALD_VENDOR` (dev: repo `vendor/`; production: resources).
  3. Line-buffered stdout reader → JSON parse → route responses by `id` and notifications to subscribers; stderr → log file.
  4. Request API with per-request timeouts (default 30 s for sync methods; jobs return quickly and then use notifications).
  5. Crash handling: on unexpected exit, reject pending requests, emit `core.crashed`, restart once; after a second crash within 60 s, stay down and show the error.
  6. Graceful shutdown on app quit: `system.shutdown`, then kill after 3 s.
  7. `powerSaveBlocker` active while any render job runs, released when none do.
- **Acceptance:** calling `system.info` from main returns versions; killing the core process by hand triggers one restart.
- **Tests:** Vitest with a fake core script (a small Node script that answers JSON-RPC) for routing, timeout and crash/restart; a unit test for the power-save toggling.

### T06.3 Typed RPC bridge and type generation
- **Depends on:** T06.2, T01.4
- **Size:** S
- **Read:** B8, C5 rule 6
- **Do:**
  1. `npm run gen:types`: runs the core schema export (T01.4), then `json-schema-to-typescript` into `src/shared/rpc-types.ts` (header comment: generated, do not edit). Add a CI check that regenerating produces no diff.
  2. A typed method map in `src/shared/rpc-methods.ts` (method name → params type → result type) using the generated types.
  3. Preload exposes `window.skald = { rpc(method, params), onNotification(method, handler) → unsubscribe, openFileDialog(...), saveFileDialog(...), openFolderDialog(...), openExternal(url) }`, with input validation in main and allowlisted IPC channels.
  4. Renderer hooks: `useRpc`, `useJob(jobId)` (tracks progress and status from notifications).
  5. Fill in the "Regenerate TypeScript types" row of the Quick commands table in `AGENTS.md`.
- **Acceptance:** the renderer calls `system.info` with full type checking; a misspelled method name fails `typecheck`.
- **Tests:** unit tests for `useJob` state transitions with mocked notifications.

### T06.4 UI foundation: theme, base components, layout
- **Depends on:** T06.1
- **Size:** M
- **Read:** B10, A6 (accessibility)
- **Do:**
  1. Tailwind with design tokens (colours, spacing, radius, typography) as CSS variables; light and dark themes; follow the OS with a manual override stored in settings.
  2. Base components (Radix-based, in `src/renderer/components/ui/`): Button, IconButton, Input, Textarea, NumberInput (unit suffix, min/max/step), Select, Checkbox, Switch, Slider, Tabs, Dialog, Tooltip, Toast, Badge, Table primitives, EmptyState, Spinner, ProgressBar.
  3. Workspace layout per B10: step navigation on the left with status badges, main area, resizable inspector on the right, collapsible Jobs drawer at the bottom, and a **Models** button in the top bar. Routing between Home and Workspace.
  4. Visible keyboard focus; every interactive component reachable by keyboard.
- **Acceptance:** a dev-only "kitchen sink" route shows every component in both themes; the layout has no overflow at 1280×720.
- **Tests:** render tests for components with interactive behaviour (Dialog, NumberInput clamping, Slider keyboard control).

### T06.5 Audio player and safe media protocol
- **Depends on:** T06.4
- **Size:** S
- **Read:** A6 (accessibility), B9
- **Do:** Register a custom protocol `skald-media://` in main that serves only files under the open project folder, `<userData>/voices/` and the preview cache (path allowlist, no `..`, read-only). `AudioPlayer` component (play/pause, seek, speed, keyboard shortcuts, accessible labels) and a compact `PlayButton`.
- **Acceptance:** plays chunk and preview files; requests outside the allowlist are refused.
- **Tests:** protocol path tests; player render tests.

### T06.6 End-to-end test harness
- **Depends on:** T06.3
- **Size:** S
- **Read:** C3.1
- **Do:** Playwright configured to launch the dev build of Electron with the real core; a smoke test: the app opens and a temporary debug panel (or About) shows `system.info` versions. `npm run test:e2e`. CI job on `windows-latest` and on Linux with `xvfb-run`.
- **Acceptance:** the smoke test passes in CI on Windows and Linux.
- **Tests:** the smoke test.

---

## D10. Phase 7 — Workflow UI

Every UI task includes loading, empty and error states; keyboard access; both themes; a screenshot in the handoff; and a short manual check by the owner on Windows (the Orchestrator writes the steps).

### T07.1 Home screen and projects
- **Depends on:** T06.3, T06.4, T02.7
- **Size:** M
- **Read:** B9, B10
- **Do:** Home with New audiobook (file picker for EPUB/TXT/MD + project folder → `project.create` + `book.import` with progress), Open, Recent (stored in `userData/recent.json`, max 10, missing ones removed), Try a sample (a bundled short public-domain story). Opening a project moves to the Workspace with a Zustand project store.
- **Acceptance:** create, close and reopen from Recent works; the sample opens at the Book step.
- **Tests:** store tests; e2e: create a project.

### T07.2 Models screen (Upscayl-style picker)
- **Depends on:** T06.3, T06.4, T03.2, T03.3, T03.6
- **Size:** M
- **Read:** B4, B10, D3
- **Do:** Grid of model cards per B10; filter by the book's language; a details drawer (checkpoints, languages, parameters, watermark note, model card text, license link); Install with pack and file progress in the Jobs drawer; a **non-commercial acknowledgement dialog** (license name and link, plain-language "You may use audio from this model for personal, non-commercial purposes only", checkbox, Accept → `license.accept`); Remove with confirmation; incompatible entries greyed out with the reason; fit rating with an explanation tooltip.
- **Acceptance:** Kokoro shows as installed; installing a fake non-commercial model in dev requires acceptance; a "Not supported" model explains why.
- **Tests:** component tests with mocked RPC.

### T07.3 Model updates and retired models
- **Depends on:** T07.2
- **Size:** S
- **Read:** B4.1, D4, D5
- **Do:** A top-bar badge when `update_available`; an update card with size and changelog line; Update installs the new revision and explains that existing projects keep their version ("Projects using the old version: …" with a "Switch this project" action that warns the voice may change); retired models labelled; "Free up space" lists unpinned old revisions.
- **Acceptance:** with a fake catalog revision bump: the badge appears, the update installs, and the open project still renders with its pinned revision.
- **Tests:** component tests.

### T07.4 Book view
- **Depends on:** T07.1, T06.5
- **Size:** M
- **Read:** C1.1, C1.2, B10
- **Do:** Chapter list with include/skip toggles and suggested-skip badges; paragraph view (virtualized) with inline editing, "play from here" preview with the narrator voice, language selector, word and character counts, unbalanced-quote flags.
- **Acceptance:** skips and edits persist and update the `render.plan` counts.
- **Tests:** component tests.

### T07.5 Voices: library, presets, cloning
- **Depends on:** T06.5, T05.1
- **Size:** M
- **Read:** D15, B10
- **Do:** Voice library grid with play buttons; Presets tab (by installed model, filterable by language and gender where provided); blend editor where supported; style sliders generated from the adapter's parameter schema (ranges and defaults); Clone tab: choose a local file, trim preview, optional transcript, **consent checkbox** (required), create. Rename and delete voices.
- **Acceptance:** create a preset voice and a cloned voice (fake adapter in dev) and preview both.
- **Tests:** component tests; consent required.

### T07.6 Voice design UI
- **Depends on:** T07.5, T05.2
- **Size:** S
- **Read:** D16
- **Do:** Design tab: description field with examples, model picker (installed design-capable models), Generate (3 candidates with players), pick one → name it → saved as a frozen voice; a short explanation of why designs are frozen.
- **Acceptance:** the fake-adapter flow works; the tab is disabled with an explanation when no design-capable model is installed.
- **Tests:** component tests.

### T07.7 Assignments and pronunciation lexicon UI
- **Depends on:** T07.4, T05.3, T02.7
- **Size:** M
- **Read:** C1.2, B10
- **Do:** Assignment panel (narrator, dialogue-voice toggle, per-chapter overrides in the chapter list, per-paragraph overrides from the paragraph context menu); lexicon editor (word, replacement, case-sensitive, whole-word; match counts; "preview this rule" plays a sentence containing the word).
- **Acceptance:** overrides show in the Book view; a rule's preview plays the respelled word.
- **Tests:** component tests.

### T07.8 Render screen
- **Depends on:** T07.7, T05.5
- **Size:** M
- **Read:** C1.4, B10
- **Do:** Plan summary (chunks cached / to do, estimated time per installed tier), Start / Pause / Resume, progress and ETA, current position, virtualized chunk table (status, QC result, play, re-render, re-render with a new seed), "Needs review" filter, sleep-prevention notice.
- **Acceptance:** render a short book with Kokoro; pause and resume; close and reopen the app mid-render and resume.
- **Tests:** component tests with mocked notifications.

### T07.9 Export dialog
- **Depends on:** T07.8, T05.7
- **Size:** S
- **Read:** C1.5
- **Do:** M4B (title, author, narrator credit, cover from the book or a chosen image) and/or MP3 per chapter; destination folder; credits preview; non-commercial notice when relevant; "Show in folder" on success.
- **Acceptance:** exports to a folder with spaces and non-ASCII characters in its path.
- **Tests:** component tests.

### T07.10 Settings and About
- **Depends on:** T06.4, T06.3
- **Size:** S
- **Read:** A6, B9
- **Do:** Settings (persisted in `userData/settings.json`): theme, model storage folder (moving it follows T03.4's recommendation, with a size warning), CPU threads, preferred GPU, idle unload time, default pauses (advanced), open logs folder. About: versions (`system.info`), app license, third-party notices, model licenses, repository link, how to cite.
- **Acceptance:** settings persist across restarts and take effect.
- **Tests:** settings store tests.

### T07.11 Error handling UX
- **Depends on:** T07.8
- **Size:** S
- **Read:** B8 (error kinds)
- **Do:** Map every `SkaldError.kind` to a friendly title, explanation and suggested action (`src/renderer/errors/messages.ts`), with specific help for `epub_drm`, `out_of_memory`, `not_enough_disk`, `pack_install_failed` (Retry and Open logs) and `license_not_accepted`. A global React error boundary with "Copy details" and "Open logs"; a core-crash banner with Restart; network errors explain the offline state. A test that every error kind declared in the core (exported from the schemas) has a message.
- **Acceptance:** forcing each of the listed errors shows a helpful message.
- **Tests:** error-kind coverage test; error boundary render test.

### T07.12 Full-flow end-to-end test — Milestone M2
- **Depends on:** T07.1–T07.11, T06.6
- **Size:** S
- **Read:** —
- **Do:** Playwright: sample project → skip one chapter → add a lexicon rule → pick a Kokoro voice → render → export M4B and MP3 to a temporary folder with a space and a non-ASCII character in its name → files exist and `ffprobe` shows the expected chapter count.
- **Acceptance:** passes on Windows CI.
- **Tests:** the e2e test.

---

## D11. Phase 8 — Verification

### T08.1 Long-book soak test
- **Depends on:** T05.8
- **Size:** S
- **Read:** A6
- **Do:** `scripts/soak.py`: render a full-length public-domain novel with Kokoro on CPU through the CLI; sample memory every 30 s; kill the process at a random point twice and resume; record total time, characters per second, peak memory, disk used and QC failure count. Run on the owner's laptop (Windows) and in a cloud session (Linux); write `docs/verification/soak-<date>.md`.
- **Acceptance:** memory shows no growth trend beyond 10 %; resumes complete without redoing chunks; report written.
- **Tests:** —

### T08.2 Release-candidate GPU self-test [GPU] [REVIEW]
- **Depends on:** T04.4, T04.5, T04.6, T04.8
- **Size:** S
- **Read:** C3.6
- **Do:** The owner runs the notebook on `main` with `MODELS = "all-gpu"` (T4; a rented GPU for any model that doesn't fit). A Builder turns the reports into `docs/verification/gpu-selftest-<date>.md` and updates the catalog's `hardware` blocks and the model cards with the measured VRAM and RTF, via a normal PR.
- **Acceptance:** every active GPU checkpoint passes its thresholds; the catalog numbers match the report.
- **Tests:** —

### T08.3 Listening review checklist and first review [REVIEW] — Milestone M3
- **Depends on:** T08.1, T08.2, T07.12
- **Size:** S
- **Read:** C1, C3
- **Do:** `docs/verification/listening-checklist.md`, per active model: numbers and abbreviations, names, dialogue switching, long sentences, chapter transitions, consistency of a frozen designed voice across 3 chapters, clone similarity (the owner's own voice, with consent), loudness consistency between chapters; plus links to the soak and GPU reports. Generate the review set with the CLI; leave sign-off lines.
- **Acceptance:** checklist completed and signed off by the owner.
- **Tests:** —

---

## D12. Phase 9 — Packaging and release

### T09.1 Freeze the core with PyInstaller [SPIKE] [STRONG MODEL]
- **Depends on:** T05.8
- **Size:** M
- **Read:** B2, D6
- **Do:** `core/skald-core.spec` (one-folder mode) bundling lxml, onnxruntime, kokoro-onnx, misaki and its data (plus any spaCy model the G2P spike requires), pysbd and soundfile/libsndfile; the `--worker kokoro` mode works from the frozen executable. Build on Windows and Linux in CI; smoke test: `--version`, `system.info`, render the bundled sample story with Kokoro, export M4B. Measure size. If freezing fails or is fragile, evaluate shipping the core as python-build-standalone + a venv (both are already bundled) and record the decision in `docs/spikes/core-packaging.md`.
- **Acceptance:** the frozen core passes the smoke test on both OSes; size recorded.
- **Tests:** CI smoke step.

### T09.2 electron-builder configuration and production paths
- **Depends on:** T09.1, T06.2
- **Size:** S
- **Read:** D20, D26
- **Do:** `electron-builder.yml`: appId `io.github.<owner>.skald`, productName `Skald`; `extraResources`: frozen core → `core/`, `vendor/ffmpeg`, `vendor/uv`, `vendor/python` (python-build-standalone), the `skald_worker` wheel, Kokoro model files, the fallback catalog and the sample story; Windows target NSIS (per-user install, no admin, desktop and Start menu shortcuts, uninstaller); Linux targets AppImage and deb; placeholder icon in `app/build/`. Update production path resolution in `core.ts`. Exclude dev files. Check the installer is under 600 MB.
- **Acceptance:** installers build; the installed app renders the sample offline.
- **Tests:** covered by T09.5.

### T09.3 Release workflow
- **Depends on:** T09.2
- **Size:** M
- **Read:** D20
- **Do:** `.github/workflows/release.yml` triggered by tags `v*`: matrix `windows-latest` + `ubuntu-latest`; set up Python and Node; run setup and `fetch_deps.py`; build the worker wheel and the frozen core; build the Electron app; run the packaged-app smoke test (T09.5); run `catalog.validate --release --network` and fail if fewer than 3 compatible active models; compute `SHA256SUMS.txt`; create a **draft** GitHub Release with the installer, AppImage, deb and checksums. The version comes from the tag and must match `app/package.json`, the core and the worker (fail otherwise).
- **Acceptance:** pushing a test tag (e.g. `v0.0.1-test`) creates a draft release with all artifacts.
- **Tests:** the workflow run.

### T09.4 Third-party and model notices
- **Depends on:** T09.1
- **Size:** S
- **Read:** D10, D12
- **Do:** `scripts/gen_notices.py`: collect licenses of bundled Python packages (from the core build venv's package metadata), npm production dependencies (`package.json` license fields and license files), ffmpeg (LGPL text, build configuration and source link), uv, python-build-standalone and the Kokoro weights, plus any GPL executable shipped per T03.9 (with its source offer); write `THIRD_PARTY_NOTICES.md`; fail on GPL, AGPL or unknown licenses for **in-process** components (print the package). Generate `MODEL_LICENSES.md` from the catalog (each model, license, commercial flag, link). Ship both inside the app (About) and with releases.
- **Acceptance:** notices generated; no forbidden licenses.
- **Tests:** CI step runs the script.

### T09.5 Packaged-app smoke test on CI
- **Depends on:** T09.2, T06.6
- **Size:** S
- **Read:** —
- **Do:** Playwright test that launches the **packaged** app (unpacked directory output) on Windows and Linux: About shows versions; open the sample; render with Kokoro; export M4B — with the HTTP helper set to refuse all requests (an env flag), to prove offline operation.
- **Acceptance:** passes in the release workflow.
- **Tests:** the smoke test.

### T09.6 README, CONTRIBUTING (with Colab button), CITATION.cff
- **Depends on:** T07.12
- **Size:** S
- **Read:** A2, D15, D18–D20
- **Do:** User-facing `README.md`: what Skald is, screenshots (from the T07 handoffs), download links, install steps for Windows (including the SmartScreen "More info → Run anyway" note while unsigned) and Linux (AppImage: make executable and run; deb: `sudo apt install ./file.deb`), a 5-minute quickstart with the sample, how to choose a model, licenses in plain words, voice-cloning consent, supported platforms (Windows primary, Linux, macOS not yet), how to report issues. Complete `CONTRIBUTING.md` (prerequisites from C4, setup script, `AGENTS.md` pointer, the "Testing on a GPU" section from T04.3). `CITATION.cff` for the software.
- **Acceptance:** the owner can follow the README on a clean Windows machine.
- **Tests:** —

### T09.7 SignPath code signing [REVIEW]
- **Depends on:** T09.3, repository public
- **Size:** S
- **Read:** D20
- **Do:** Prepare the SignPath Foundation application (project description, repository link, build process description) for the owner to submit. After approval, add SignPath's GitHub Action to the release workflow to sign the Windows installer and executables; add `docs/code-signing.md` (the code signing policy page SignPath requires, including the "Free code signing provided by SignPath.io, certificate by SignPath Foundation" credit and the project roles) and link it from the README.
- **Acceptance:** a draft release's Windows installer shows "SignPath Foundation" as the signer.
- **Tests:** verify the signature on the CI runner (`Get-AuthenticodeSignature`).

### T09.8 Release checklist and v0.1.0 — Milestone M4
- **Depends on:** T08.3, T09.3–T09.6
- **Size:** S
- **Read:** C3.1 (release gate)
- **Do:** `docs/release-checklist.md`: versions bumped, CI green, catalog `--release` check passed, GPU self-test reports current, listening review signed, notices regenerated, README screenshots current, draft release tested on a clean Windows PC and a Linux machine, release notes written. Walk through it for v0.1.0 and publish.
- **Acceptance:** v0.1.0 is public on GitHub Releases.
- **Tests:** —

---

## D13. Phase 10 — Backlog (not yet broken into tasks)

Ordered roughly by expected value. Each needs a short design note before tasks are written.

1. **macOS build** (Apple Silicon; most packs need an MPS or CPU lock; Kokoro works via ONNX).
2. **AMD/Intel GPU acceleration** — ONNX Runtime DirectML/WebGPU for Kokoro; VoxCPM2 GGUF via llama.cpp-omni or VoxCPM.cpp (CPU/CUDA/Vulkan), which would also give VoxCPM2 a usable CPU tier.
3. **More import formats** — PDF (text layer), DOCX, MOBI/AZW3 (license-checked libraries only).
4. **Character voices** — automatic speaker attribution for dialogue (probably a small local LLM), one voice per character.
5. **Read-along** — word timestamps and EPUB 3 Media Overlays or subtitles.
6. **In-app quality check** with a small Whisper model (optional download).
7. **Batch conversion** of a folder of books.
8. **"Render on Colab" notebook for users** without a GPU, using the headless CLI.
9. **Voxtral TTS / Higgs Audio** if Windows-native single-process inference appears (D7).
10. **Phoneme-level lexicon** for Kokoro.
11. **Signed catalog** (e.g. a minisign signature checked by the app, key held by the owner).
12. **ModelScope mirror** for users who can't reach Hugging Face.
13. **Parallel rendering** across GPU and CPU workers.
14. **Project website and own domain** (then change the app ID, D26).

---

## Appendix 1 — Glossary

- **TTS:** text-to-speech.
- **Model family / checkpoint / revision:** "Qwen3-TTS" (family) → "1.7B VoiceDesign" (checkpoint) → one pinned upstream commit (revision).
- **Adapter:** our small module that drives one model family through its official package.
- **Engine pack:** the Python environment a family's worker runs in (B5).
- **Worker:** the process that loads a model and synthesizes chunks (B6).
- **Chunk:** the unit of text sent to a model in one call (a few sentences).
- **RTF (real-time factor):** generation time ÷ audio duration. RTF 0.5 = twice as fast as real time.
- **G2P:** grapheme-to-phoneme — turning spelling into pronunciation symbols.
- **Voice design / cloning:** creating a voice from a text description / from a reference recording.
- **M4B:** an MP4 audio file with chapters, the usual audiobook format.
- **LUFS:** loudness units relative to full scale; how loud audio sounds on average.
- **WER / CER:** word / character error rate of a transcript against the original text.
- **Non-commercial (NC) license:** the model and its output may be used only for personal, non-commercial purposes.
- **Spike:** a short investigation whose output is a findings document, not product code.

## Appendix 2 — Prompt templates

**Build a task**
> Read `AGENTS.md`, then read `SPEC.md` Parts A–C and task **TXX.Y** in Part D. Implement only that task. Follow its acceptance criteria and run its tests. If anything in the spec is ambiguous or seems wrong, stop and ask instead of guessing. When finished, tick the task in the Part D task index and give me a short summary of what changed, what you tested, and anything you were unsure about.

**Review a finished task** (use a fresh session, ideally a different model)
> Read `AGENTS.md`, `SPEC.md` Parts A–C and task **TXX.Y**. Review the changes in the latest commit(s) for this task against its acceptance criteria, the defaults in C1, the decisions in A5 and the agent rules in C5. Run the task's tests. List concrete problems with file and line references, ordered by severity. Do not fix anything.

**Fix a failing test without cheating**
> Test `<name>` fails. Find the root cause. You may not change golden files, intelligibility thresholds, catalog checksums or test expectations unless you can show the expectation itself is wrong — in that case stop and explain instead of changing it.

**Clean up before abandoning the project**
> Read `CLEANUP.md`. Walk me through removing everything it lists, one step at a time, starting with the project folder and the app's data folder.

## Appendix 3 — Clarifications log

Answers from the Orchestrator (or owner) that clarify or change this spec are recorded here by the Builder in the same PR, newest last. Decisions that change Part A are also added to the decision log.

| Date | Task | Question | Answer | Decided by |
|---|---|---|---|---|
| — | — | — | — | — |

## Appendix 4 — Claude Code cloud environment

One environment named **Skald**, used by every Claude session (Orchestrator, Reviewers, Claude Builders). Other agents' cloud environments (e.g. Codex) need the same domains and tools.

**Where:** at claude.ai/code, the environment selector is the first control under the message box on the new-session screen → **New environment**.

**Network access:** **Custom**, with **Also include default list of common package managers** checked (covers PyPI, npm, GitHub including release downloads and raw files, and Ubuntu mirrors). **Allowed domains**, one per line:

```text
huggingface.co
*.huggingface.co
*.hf.co
download.pytorch.org
www.gutenberg.org
```

(Hugging Face's CDN hostnames change from time to time; if downloads fail, check the redirect host in the error and add it.)

**Environment variables:** none.

**Setup script:**

```bash
#!/bin/bash
# Skald cloud setup. Must exit 0 and finish within ~5 minutes so it gets cached.

# Python 3.12 — Ubuntu 24.04 normally has it; install with uv only if missing.
if ! command -v python3.12 >/dev/null 2>&1; then
  uv python install 3.12 || true
  P="$(uv python find 3.12 2>/dev/null)" && ln -sf "$P" /usr/local/bin/python3.12 || true
fi

# venv support for the system Python, plus the libraries Electron needs for headless tests (xvfb).
apt-get update -qq || true
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  python3.12-venv xvfb libgtk-3-0t64 libnss3 libasound2t64 libgbm1 libxss1 libxtst6 >/dev/null 2>&1 || true

python3.12 --version || true
node --version || true
exit 0
```
