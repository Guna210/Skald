# CLEANUP.md

Everything Skald puts on your computer, and how to remove it. Agents and contributors must add any approved global install here, with its exact removal command.

## Global prerequisites

These are the only things installed outside the project folder.

| Tool | Version | Approx. size | Remove with |
|---|---|---|---|
| Git | latest | ~0.4 GB | Windows "Apps & features" / `apt remove git` |
| Python | **3.12.x** (python.org installer on Windows) | ~0.15 GB | Windows "Apps & features" |
| Node.js | **24.x LTS** (22.x also accepted; cloud sessions may ship 22) | ~0.1 GB | Windows "Apps & features" |
| Editor (e.g. VS Code) | any | ~0.5 GB | its uninstaller |

Agent command-line tools (Claude Code, Codex), if installed locally, are also global. List each one here with its removal command when you install it.

## Project-local items

All of these live inside the repository folder and disappear when you delete it.

| Path | What it is | Approx. size |
|---|---|---|
| `core/.venv/` | The core's development environment (no PyTorch) | ~1 GB |
| `app/node_modules/` | The desktop app's Node packages | varies |
| `.cache/` | pip, uv, npm and Electron caches (`.cache/uv`, `.cache/pip`, `.cache/npm`, `.cache/electron`, `.cache/electron-builder`), development engine packs (`.cache/packs/`, 1–5 GB each) and a stand-in for the app's data folder (`.cache/devdata/`: models, packs, voices) | several GB |
| `vendor/` | ffmpeg, uv and Python for the current OS, fetched by `scripts/fetch_deps.py` | varies |

To free space without deleting the repository, delete the folder you no longer need (for example `.cache/packs/<pack>`).

## The installed app's data

The installed app keeps downloaded models, engine packs and saved voices in its user-data folder, not in the repository:

| OS | Folder |
|---|---|
| Windows | `%APPDATA%\Skald` |
| macOS | `~/Library/Application Support/Skald` |
| Linux | `~/.config/Skald` |

It contains `models/`, `packs/`, `uv-cache/`, `voices/`, `logs/` and settings files. To delete everything the app downloaded, close the app and delete that folder. If you moved model storage with Settings → "Model storage folder", delete that folder as well. Your audiobook projects are separate folders you chose yourself; the app never deletes them.

## Full removal

1. Close Skald.
2. Delete the repository folder (this removes everything under "Project-local items").
3. Uninstall the Skald app (Windows "Apps & features"; Linux: remove the `.deb` with your package manager, or delete the AppImage).
4. Delete the app's data folder (table above), plus the model storage folder if you moved it.
5. Delete any audiobook project folders you no longer want.
6. If you no longer need them for anything else, uninstall the global tools: Git, Python, Node.js, your editor and any agent command-line tools.
