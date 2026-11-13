# Spike T03.4 — engine packs (uv + python-build-standalone + hash-locked PyTorch)

Status: findings for Orchestrator/owner review. Input for T03.5 (pack builder).
Date of measurements: 2026-11-13. uv 0.13.8, vendored CPython 3.12.16 (python-build-standalone 20261110), torch 2.14.1.

**Every number below was measured** by `docs/spikes/scripts/spike.py` unless the sentence says *estimate* or *not measured*.
Raw results: `docs/spikes/scripts/results/` (`cloud-linux.json` full; `ci-linux.json`, `ci-windows.json` condensed from the job logs).

## 1. Summary

B5 works as designed on Linux (ext4) and Windows (NTFS), with these corrections:

1. **Use `--torch-backend <cpu|cu126>`, not a hand-written index URL**, both when locking and when syncing. Every hand-written index combination tried either took PyTorch from the wrong index or took old dependencies from PyTorch's mirror (section 3.1).
2. **A new host is needed: `download-r2.pytorch.org`.** PyTorch's index pages are on `download.pytorch.org`, but the wheel files are served from `download-r2.pytorch.org`. PyPI is two hosts: `pypi.org` and `files.pythonhosted.org`.
3. **`uv cache prune` frees nothing when a pack is removed.** Wheels of removed packs stay in the cache (784.1 MB on Linux, 528.8 MB on Windows after removing all but one CPU pack). Only `uv cache clean` frees them; existing packs keep working after it.
4. **The cache and the packs must be on the same volume.** Otherwise uv silently copies instead of hard-linking: every pack costs its full size and the cache keeps a second copy.
5. **Do not move packs. Move (or drop) the cache and rebuild.** With the cache copied to the new volume, rebuilding the CPU pack offline took 0.13 s (Linux) / 1.27 s (Windows).
6. **Windows path length matters.** A CPU pack whose folder path was 161 characters worked; at 202 characters `import torch` failed, with or without the Windows long-path switch. Keep the pack folder path ≤ 150 characters and pack folder names ≤ 40 characters.
7. **The lock hash must be computed on LF-normalised bytes.** A Windows checkout (`core.autocrlf=true`) turns the lock files into CRLF and changes their SHA-256 (`374fd357` instead of `acf54e6a`).
8. **Trust the OS certificate store (`UV_SYSTEM_CERTS=1`)** so installs work behind TLS-inspecting proxies. Never disable verification.
9. **CUDA pack = `cu126` with torch 2.14.1.** torch 2.15.0 has no CUDA 12 builds at all (only `cpu`, `cu132`, `cu134`). The compiled architecture list covers Pascal and Turing.
10. **Antivirus is the main Windows cost:** the CPU pack's cold install took 18.54 s with Defender real-time scanning off and 88.98 s with it on.

## 2. Method

| Machine | Where | Filesystems | Notes |
|---|---|---|---|
| Cloud Linux | Claude Code cloud container, 4 CPUs | ext4; second volume `/dev/shm` (tmpfs) | Behind a TLS-inspecting proxy, so this machine supplied the TLS measurements. |
| CI Linux | GitHub `ubuntu-latest`, 4 CPUs | ext4 `/`; second volume `/dev/shm` (tmpfs; `/mnt` is the same device as `/`) | Direct internet. |
| CI Windows | GitHub `windows-latest`, 4 CPUs | NTFS `C:` (packs and cache) and NTFS `D:` (checkout, second volume) | `core.autocrlf=true`, `LongPathsEnabled=1`, Defender real-time scanning **off** and `C:\`, `D:\` excluded by default. |

Spike workflow runs (temporary workflow, deleted from the branch in the last commit):

| Run | Link | Result |
|---|---|---|
| 1 | https://github.com/Guna210/Skald/actions/runs/43469906492 | Linux OK; Windows setup step failed (workflow mistake). |
| 2 | https://github.com/Guna210/Skald/actions/runs/43470883244 | Superseded by run 3. |
| 3 | https://github.com/Guna210/Skald/actions/runs/43470985145 | Linux OK; Windows stopped at the long-path step (harness crash, fixed). |
| 4 | https://github.com/Guna210/Skald/actions/runs/43472375698 | **Linux and Windows complete.** Source of all CI numbers below. |
| 5 | https://github.com/Guna210/Skald/actions/runs/43475133643 | Windows only: extra long-path lengths (section 3.7). |

Sample packs (`docs/spikes/scripts/torch-cpu/`, `torch-cu12/`): `torch==2.14.1` + `numpy`. B5 steps 3–4 were replaced by a dummy local wheel installed with `--offline --no-index --no-deps` and `check_pack.py` (imports torch and numpy, prints versions, `cuda.is_available()` and the compiled CUDA architecture list).

Reproduce: `core/.venv/bin/python docs/spikes/scripts/spike.py lock --check`, then `… spike.py measure --work <empty folder> [--other-volume <folder on another volume>] [--packs cu12]`.

## 3. Findings (the task's questions)

### 3.1 Lock generation

Command that works (one call per pack × OS):

```bash
uv pip compile packs/<family>/requirements.in \
  --generate-hashes --only-binary :all: \
  --python-version 3.12 --python-platform <x86_64-manylinux_2_28 | x86_64-pc-windows-msvc> \
  --torch-backend <cpu | cu126> \
  --exclude-newer <UTC timestamp recorded in make_locks.py> \
  --emit-index-annotation --custom-compile-command "python scripts/make_locks.py" \
  -o packs/<family>/locks/<os>-<accel>.txt
```

- **One machine can generate both OSes.** All four locks were generated on the cloud Linux machine. `spike.py lock --check` regenerated them byte-for-byte identically on CI Linux and CI Windows (after LF normalisation), and the Windows runner installed from the Windows locks generated on Linux with `--require-hashes`.
- **Resulting locks:** CPU: 11 packages, identical text for Linux and Windows. cu12 Linux: 30 packages (torch and triton from the PyTorch index; 17 `nvidia-*-cu12`/`cuda-*` wheels from PyPI). cu12 Windows: 11 packages (the CUDA libraries are inside the torch wheel).
- **Index strategy (supply chain).** What was tried:

  | Attempt | Result |
  |---|---|
  | `--index-url <pytorch cu126> --extra-index-url pypi` | Dependencies came from PyTorch's mirror, which is stale (filelock 4.2.4, setuptools 78.1.0). |
  | `--index-url pypi --extra-index-url <pytorch>` with `torch==2.14.1` | **Silently resolved torch from PyPI** (the CUDA 13 build). |
  | Same with `torch==2.14.1+cpu` | Fails: uv stops at the first index that has the package name. |
  | `--torch-backend <cpu\|cu126>` | Correct: torch (and triton) from `download.pytorch.org/whl/<backend>`, everything else from PyPI. |

  With `--emit-index-annotation` every pin carries a `# from <index>` line. The spike locks contain 48 pins from `https://pypi.org/simple`, 1 from `…/whl/cpu` and 3 from `…/whl/cu126`. **make_locks.py should fail if any package other than an explicit allowlist (`torch`, `triton`, later `torchaudio`/`torchvision` if a pack needs them) is annotated with a PyTorch index, or if `torch` is annotated with PyPI.**
- `--only-binary :all:` makes locking fail rather than pin a source distribution; `uv pip sync --no-build` enforces the same at install time. `--exclude-newer` makes regeneration reproducible (measured: identical output on three machines hours apart).
- **Locks are specific to the Python version.** A 3.11 lock from the same input differs (numpy 2.4.6 vs 2.5.4, networkx 3.6.1 vs 3.7).
- `spike.py`'s first version let uv write to `~/.cache/uv`; make_locks.py must set `UV_CACHE_DIR` (and `UV_NO_CONFIG=1`) so nothing outside the project is touched.

### 3.2 `uv venv` with the vendored Python

`uv venv --python <vendored python> --no-project <pack dir>` works on both OSes: 0.04–0.26 s cold, 0.01–0.03 s warm. `UV_PYTHON_DOWNLOADS=never` guarantees uv uses the given interpreter or fails.

`pyvenv.cfg` stores the **absolute** path of the base Python (`home = …/vendor/python/linux64/bin`), also with `--relocatable`. If the base Python moves, the pack's Python does not start (Linux: "No such file or directory"; Windows: "No Python at …"). Re-pointing an existing pack with `uv venv --allow-existing --python <new base> <pack dir>` took 0.07–0.14 s and the installed packages still imported.

### 3.3 `uv pip sync --require-hashes`

```bash
uv pip sync --python <pack python> --require-hashes --no-build --torch-backend <cpu|cu126> <lockfile>
```

- Works on both OSes, including from a CRLF lock file on Windows.
- `--torch-backend` is needed at sync time too (it tells uv where torch lives; a lock file carries no index URLs that uv acts on).
- **Tamper test:** with one hash changed in the lock, sync failed with `Hash mismatch` (exit 1) both with a warm cache (0.05–0.15 s) and a cold one; nothing but the 16–17 files of the empty venv was on disk afterwards.
- **`uv pip sync` removes anything not in the lock**, so re-syncing (repair) uninstalls the `skald_worker` wheel: step 3 must run after every sync, with `--no-deps`, and the worker's own dependencies must be in the pack lock.
- Dummy wheel install, no network (`uv pip install --python <pack python> --offline --no-index --no-deps <wheel>`): 0.02–0.24 s.

### 3.4 Hard-link deduplication and disk use

Same volume for cache and packs, `UV_LINK_MODE=hardlink`:

| | ext4 (CI Linux) | NTFS (CI Windows) |
|---|---|---|
| CPU pack, cold: free-space drop | 868.1 MB | 623.1 MB |
| CPU pack size (du) | 830.9 MB, 16,955 files | 577.5 MB, 16,778 files |
| Pack + cache, counting each file once | 835.2 MB | 581.7 MB |
| Second CPU pack from the same lock: free-space drop | **7.3 MB** | **11.9 MB** |
| Both packs, counting each file once | 832.6 MB | 579.9 MB |
| Link count of the largest file after two packs | 3 (cache + 2 packs) | 3 |
| cu12 pack, cold: free-space drop | 6,669.0 MB | 4,326.4 MB |
| cu12 pack size | 6,627.7 MB, 17,942 files | 4,293.4 MB, 16,813 files |
| Second cu12 pack: free-space drop | 8.3 MB | 10.4 MB |

So a pack costs its size once; further packs from the same wheels cost ~10 MB each. `du` on a single pack reports the full size (it cannot know the files are shared), so the UI should not add up pack sizes.

**Cache on a different volume** (cache on the second volume, packs on the first): uv prints `Failed to hardlink files; falling back to full copy` once and carries on. Link count 1; the pack volume lost 858.0 MB (Linux) / 598.7 MB (Windows) **and** the cache volume lost 855.3 / 617.0 MB; a second pack cost another 858.1 / 613.8 MB. No error, just double the disk and no sharing.

**Removing packs.** After deleting all but one CPU pack, `uv cache prune` reported "No unused entries found" and freed 0 MB (cache 1,596.0 MB before and after on Linux, 1,086.7 MB on Windows; of that, 784.1 / 528.8 MB was not linked from any remaining pack). `uv cache clean` freed 828.8 MB (Linux, 2.09 s) / 579.5 MB (Windows, 6.32 s) and the remaining pack still worked (its files are then the only copy, link count 1).

### 3.5 Pack sizes and install times

| | Cloud Linux | CI Linux | CI Windows (Defender off) |
|---|---|---|---|
| CPU cold `uv pip sync` | 6.49 s | 2.75 s | 20.68 s |
| CPU warm sync (second pack) | 0.31 s | 0.23 s | 6.84 s |
| CPU first `import torch` + numpy | 2.91 s | 1.96 s | 7.27 s |
| CPU second import | 1.01 s | 0.67 s | 1.51 s |
| cu12 cold sync | 337.8 s | 22.21 s | 50.98 s |
| cu12 warm sync | 0.73 s | 0.23 s | 7.89 s |
| cu12 first import | 3.38 s | 2.15 s | 8.08 s |

- Download sizes (cloud Linux, sum of uv's "Downloading" lines ≥ 1 MiB): CPU 211.2 MiB (torch 187.2); cu12 Linux 3,499.5 MiB (torch 828.9, cudnn 674.0, cublas 374.9, nccl 276.3, cusparselt 273.9, triton 235.4, …). Windows download sizes were not measured.
- Install time is dominated by the network (cloud vs CI for the same 3.5 GiB: 337.8 s vs 22.21 s) and on Windows by file creation and antivirus (3.8).
- **Bytecode pre-compilation is not worth it:** `python -m compileall` took 9–16 s (Linux) / 29 s (Windows), added 127–129 MB, and import time afterwards equalled the ordinary second import (0.68 vs 0.67 s; 1.52 vs 1.51 s). Python writes the bytecode it needs on first use anyway.
- Vendored tools on disk (Linux): Python 109 MB, uv 37 MB.

### 3.6 Behind `HTTPS_PROXY`

- **Plain forwarding proxy** (`connect_proxy.py`, a logging CONNECT proxy; CI Linux and Windows): uv honours `HTTPS_PROXY`; a cold CPU install through it took 4.83 s (Linux) / 22.29 s (Windows). Hosts contacted for a pack install: `pypi.org`, `files.pythonhosted.org`, `download.pytorch.org`, `download-r2.pytorch.org`. With a Python download (3.9) additionally `releases.astral.sh`.
- **Proxy down:** fails in 4.28 s (Linux) / 14.36 s (Windows) with `tunnel error: failed to create underlying connection … Connection refused` (exit 2). No silent direct connection.
- **No proxy variable where one is required** (cloud): DNS error after 11.29 s.
- **TLS-inspecting proxy** (cloud machine; the proxy re-signs HTTPS with its own CA):

  | Setting | Result |
  |---|---|
  | uv defaults (bundled webpki roots) | Fails: `invalid peer certificate: UnknownIssuer`, with a hint to use `--system-certs`. |
  | `SSL_CERT_FILE=<CA bundle>` | Works. |
  | `UV_SYSTEM_CERTS=1` (OS trust store) | Works. |
  | `--system-certs` | Works. |
  | `--native-tls` (old name) | Still accepted; the `UV_NATIVE_TLS` variable prints a deprecation warning. |

  Recommendation: always set `UV_SYSTEM_CERTS=1` and pass the user's `HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY` and `SSL_CERT_FILE` through unchanged. A company's CA is normally in the OS store, so this works with no user setting. Never offer `--allow-insecure-host` or any switch that disables verification. Map `UnknownIssuer` to a clear message ("your network inspects HTTPS; ask IT for the certificate or install it in the system store").
- Not measured: proxies that need a username/password, and the Windows certificate store with a real corporate CA (the Windows runner has no inspecting proxy).

### 3.7 Windows long paths

Longest path inside a pack, relative to the pack folder: 143 characters (CPU), 145 (cu12) on Windows; 148/149 on Linux. They are licence texts and C++ headers, not files loaded at run time.

CPU pack installed under folders of increasing length (runs 4 and 5):

| Pack folder path length | Longest file path | `LongPathsEnabled=1` | `LongPathsEnabled=0` |
|---|---|---|---|
| 112 | 256 | works | works |
| 131 | 275 | works | works |
| 161 | 305 | works | not run |
| 202 | 346 | **fails**: `WinError 206 … Error loading torch_global_deps.dll or one of its dependencies` | **fails**: `No module named 'numpy._core._multiarray_umath'` |
| 246 (python.exe at 265) | 390 | **fails**: python.exe cannot be started (`WinError 206`) | **fails**: `WinError 2` |

- `uv venv` and `uv pip sync` **succeeded in every row** (exit 0), including 390-character paths with the long-path switch off. So a successful install proves nothing; only step 4 (the worker check) catches it.
- The Windows long-path switch does not help: Python and the DLL loader still fail.
- Linux: 199-character pack folder (longest file path 348) works.

Recommendation: on Windows refuse to install when the pack folder path would exceed **150 characters** (161 measured working, 202 failing; the exact limit in between was not measured and other model families may load deeper files) with a message asking for a shorter storage folder; warn in Settings when a chosen storage folder leaves less room than that. Keep pack folder names **≤ 40 characters**: `<family>-<os>-<accel>-<lockhash8>` with `family` ≤ 14 characters, `os` = `windows`/`linux`, `accel` = `cpu`/`cu12` (longest example `chatterbox-windows-cu12-af8b1015` = 32). With the default `C:\Users\<name>\AppData\Roaming\Skald\packs\` (43 characters for a 5-letter user name) that leaves ample room. If a later family fails the step 4 check only because of path length, shorten its name rather than changing the scheme.

### 3.8 Antivirus

Windows runner, CPU pack, cold install with its own empty cache:

| Defender state | `uv pip sync` | of which download+unpack / link into pack | First import |
|---|---|---|---|
| Real-time scanning off, drives excluded (runner default) | 18.54 s | 10.37 s / 7.66 s | 6.77 s |
| Real-time scanning on, exclusions removed | **88.98 s** | 64 s / 24.11 s | 12.99 s |

So Defender made the install 4.8× slower and the first import 1.9× slower; nothing failed and nothing was quarantined. The cu12 pack with Defender on was not measured; *estimate*: several minutes of scanning on top of the download (50.98 s with Defender off). Recommendation: show stage progress with an indeterminate "Installing (your antivirus may slow this down)" note; do not add Defender exclusions from the app (needs admin and weakens the user's protection); mention the option in the troubleshooting docs only.

### 3.9 Changing the storage folder: rebuild, don't move

- **Moving a pack folder** (plain `uv venv`): `python -c "import torch"` still works, but console scripts break (Linux: stale `#!` path; Windows: `uv trampoline failed to canonicalize script path`).
- **Moving a `uv venv --relocatable` pack**: imports and console scripts both work on both OSes. It costs nothing, so create packs with it.
- But a move to **another volume** breaks the hard links: the moved packs become full copies and the sharing in 3.4 is lost for good.
- **Rebuild instead:** copy the cache to the new folder (816.2 MB in 1.02 s on Linux; 562.1 MB in 5.9 s on Windows), then build the pack there with `UV_OFFLINE=1`: 0.13 s / 1.27 s, +1.9 / +9.1 MB, hard-linked again, check passes. No network needed.

Recommendation for the Settings task: "change model storage folder" = (1) move model files, (2) move `uv-cache` (same volume: rename; other volume: copy then delete), (3) delete the old packs and rebuild each from its lock offline, (4) run step 4 for each. If the cache was cleaned earlier, step 3 downloads again; say so in the size warning.

**Base Python location.** Because `pyvenv.cfg` holds an absolute path (3.2), packs break whenever the bundled Python's path changes: an app update that installs to a new folder, a portable copy moved by the user, or (not measured, from how AppImage works) an AppImage, which mounts at a different temporary path on every start. Recommendation: before starting a worker, compare `home` in the pack's `pyvenv.cfg` with the current bundled Python and, if different, run `uv venv --allow-existing --relocatable --python <bundled python> <pack dir>` (0.07–0.14 s measured, packages kept).

### 3.10 A pack that needs Python 3.11

- With `UV_PYTHON_DOWNLOADS=never` (the default recommended here) `uv venv --python 3.11` fails cleanly: "No interpreter found for Python 3.11 in managed installations".
- With `UV_PYTHON_DOWNLOADS=automatic` and `--managed-python`, `uv venv --python 3.11 --managed-python <pack dir>` downloads CPython 3.11.18 (python-build-standalone 20261110, `install_only_stripped`), 29.4 MiB (Linux) / 24.3 MiB (Windows), in 0.79 s / 3.85 s on CI, into `UV_PYTHON_INSTALL_DIR` (82.9 / 71.7 MB installed). It created no shim on `PATH` and wrote nothing outside the given folders. (`uv python install` without `--no-bin` does create `~/.local/bin/python3.11`; don't use it.)
- **Source:** uv 0.13.8 first tries `https://releases.astral.sh/github/python-build-standalone/releases/download/<date>/…` and falls back to `https://github.com/astral-sh/python-build-standalone/releases/download/<date>/…` (seen on the cloud machine, where the first host is blocked). Setting `UV_PYTHON_INSTALL_MIRROR=https://github.com/astral-sh/python-build-standalone/releases/download` goes straight to GitHub, which keeps B5's host list unchanged.
- **Verification:** uv checks the archive against a SHA-256 built into the uv binary. A tampered archive served from a `file://` mirror was rejected ("Expected … Computed …", exit 2) on both OSes. So the trust anchor is the pinned uv binary (itself SHA-256-pinned in `scripts/deps.lock.json`).
- The 3.11 pack then synced from a 3.11 lock and passed the check (python 3.11.18, numpy 2.4.6). The lock must be compiled with `--python-version 3.11`.
- Which 3.11 patch release is downloaded is fixed by the uv version, so it changes only when we bump uv.

Recommendation: no MVP model needs this, so T03.5 should **not** implement it; keep `UV_PYTHON_DOWNLOADS=never`. If a later pack declares another Python, use the settings in section 4.4.

### 3.11 Licences and redistribution

See `docs/spikes/deps-mirror.md` for what we bundle and mirror (uv: MIT OR Apache-2.0; CPython via python-build-standalone: PSF-2.0 plus bundled components; both are redistributable with their licence texts, which the third-party notices must include).

Additional points from this spike:

- **A Python downloaded by uv** (3.10) is the same python-build-standalone distribution, fetched by the user's machine from Astral/GitHub. Skald does not redistribute it, so no extra notice duty arises beyond listing it in the docs.
- **Pack contents are downloaded by the user's machine from PyPI / PyTorch; Skald redistributes none of them.** Licence metadata of what the sample packs pull in: torch BSD-style, with many bundled third-party licences (Apache-2.0, BSD, MIT, …) inside the wheel; numpy BSD-3-Clause and bundled components; triton MIT; `cuda-bindings` and friends as declared on PyPI; **`nvidia-*-cu12` wheels (Linux) are "NVIDIA Proprietary Software"** under NVIDIA's CUDA/cuDNN licence terms, and the Windows cu126 torch wheel contains the same NVIDIA libraries.
- **Open question for the owner/Orchestrator (not a Builder's call):** the NVIDIA libraries are proprietary. Downloading them from PyPI/PyTorch onto the user's machine at the user's request is how every PyTorch user gets them, and we never host them, but the model-install screen for GPU packs probably should say that NVIDIA's CUDA libraries are downloaded under NVIDIA's licence. The mirror rule follows: **never mirror pack wheels** in `deps-v1` or anywhere else.
- No GPL/AGPL package appeared in either sample pack's lock.

## 4. Recommended commands for T03.5

### 4.1 Environment for every uv call made by the core

```text
UV_NO_CONFIG=1              ignore the user's uv.toml / pyproject settings
UV_CACHE_DIR=<storage>/uv-cache
UV_LINK_MODE=hardlink
UV_PYTHON_DOWNLOADS=never
UV_SYSTEM_CERTS=1           OS trust store (TLS-inspecting proxies)
UV_NO_PROGRESS=1            plain log lines for the job log
```

Start from the user's environment with every other `UV_*` variable removed; keep `HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY`, `SSL_CERT_FILE`. `<storage>` is the model storage folder (default `userData`), so cache and packs share a volume.

### 4.2 Install (B5 steps 1–5)

```bash
# 1. environment (into "<name>.part"; rename to "<name>" only after step 5)
uv venv --python <bundled python> --no-project --relocatable <storage>/packs/<name>.part
# 2. packages
uv pip sync --python <pack python> --require-hashes --no-build --torch-backend <cpu|cu126> <lockfile>
# 3. worker wheel, no network
uv pip install --python <pack python> --offline --no-index --no-deps <skald_worker wheel>
# 4. check
<pack python> -m skald_worker --adapter <family> --check
# 5. write pack.json, then rename the folder
```

`<pack python>` is `<pack>/bin/python` (Linux) or `<pack>\Scripts\python.exe` (Windows). The `--torch-backend` value comes from the lock (record it in the lock header or the pack's metadata next to the lock). A venv that has been renamed still works because of `--relocatable` (3.9); if T03.5 prefers, build in place and treat a missing `pack.json` as "half-built" exactly as B5 says — both are safe.

### 4.3 Repair, remove, storage change

```bash
# repair = delete the pack folder, then 4.2 again (warm cache: 0.2 s Linux / 7 s Windows for step 2)
# remove = delete the pack folder; then, only if no pack is left (or the user asks to free space):
uv cache clean
# base Python moved (app update / AppImage):
uv venv --allow-existing --relocatable --python <bundled python> <pack dir>
# storage folder changed: move uv-cache, then for each pack 4.2 with UV_OFFLINE=1 added (falls back to online if it fails)
```

### 4.4 Only if a pack ever declares another Python version

```text
UV_PYTHON_DOWNLOADS=automatic
UV_PYTHON_INSTALL_DIR=<storage>/python
UV_PYTHON_INSTALL_MIRROR=https://github.com/astral-sh/python-build-standalone/releases/download
```

```bash
uv venv --python 3.11 --managed-python --no-project --relocatable <pack dir>
```

### 4.5 Lock generation (`scripts/make_locks.py`)

The command in 3.1, run once per pack × OS on any one machine, with `UV_NO_CONFIG=1` and a project-local `UV_CACHE_DIR`, followed by these checks: (a) index allowlist from the `# from` annotations; (b) no `--no-binary`/sdist entries; (c) lock files written with LF. Add a `--check` mode (regenerate to a temp file and compare) for CI; it passed on all three spike machines.

### 4.6 Free-disk check before install

Measured need = free-space drop of a cold install: CPU 868 MB (Linux) / 623 MB (Windows); cu12 6,669 MB (Linux) / 4,326 MB (Windows). Peak use during the install was not sampled; *estimate*: require the recorded figure × 1.2. make_locks.py cannot measure this itself, so the figure in each lock's comment header has to come from a real install (CI smoke install for CPU, the GPU notebook or this document for cu12).

## 5. Watch-outs answered

- **Supply chain:** 3.1 (torch-backend, index annotations + allowlist check, `--only-binary`, `--require-hashes --no-build`, tamper test).
- **TLS-inspecting proxies:** 3.6 (`UV_SYSTEM_CERTS=1` by default; `SSL_CERT_FILE` honoured; verification never disabled).
- **CUDA variant:** `cu126`. Available CUDA 12 backends at spike time: cu126 (up to torch 2.14.1), cu128 (stops at 2.11.0), cu129 (Linux only, 2.13.0). torch 2.15.0 ships only cpu/cu132/cu134, so the cu12 family is at its last releases; D-log/B5 should expect a `cu13` accelerator name eventually. `torch.version.cuda` = 12.6, cuDNN 9.10.2. Compiled architecture list: Linux `sm_50 sm_60 sm_70 sm_75 sm_80 sm_86 sm_90`; Windows the same plus `sm_61`. Turing (`sm_75`, e.g. the T4) is listed on both. Pascal: `sm_61` is listed on Windows; on Linux only `sm_60` is, and Pascal desktop cards are `sm_61` — CUDA normally runs `sm_60` code on them, but that was **not measured** (no GPU here). `cuda.is_available()` was `false` on all machines (no GPU), as expected. **The GPU self-test must confirm** `cuda.is_available()` and a tensor operation on the T4 (covers Turing); a Pascal card can only be confirmed by a user or the owner, so catalog `hardware` blocks should not promise Pascal until someone has.
- **Disk:** packs and caches were deleted between steps; nothing but scripts, four small lock files and three results files is committed.

## 6. Changes proposed for B5 / T03.5

Not applied; for the Orchestrator to decide.

1. **B5 inputs:** replace "with the PyTorch index URL pinned for CUDA builds" by "`uv pip compile --generate-hashes --only-binary :all: --torch-backend <cpu|cu126> --exclude-newer … --emit-index-annotation`; make_locks.py verifies that only allowlisted packages come from the PyTorch index". Record the backend per lock.
2. **B5 step 1:** add `--relocatable --no-project`; say the env is built with `UV_PYTHON_DOWNLOADS=never`.
3. **B5 step 2:** add `--no-build --torch-backend <backend>`, `UV_NO_CONFIG=1`, `UV_SYSTEM_CERTS=1`; state that `uv-cache` lives in the **model storage folder** next to `packs/` (same volume), not necessarily `userData`.
4. **B5 step 3:** worker wheel installed with `--offline --no-index --no-deps` **after every sync** (sync removes it); worker dependencies belong in each pack's `requirements.in`.
5. **B5 `<lockhash8>`:** first 8 hex characters of the SHA-256 of the lock file with CRLF converted to LF; add `packs/**/locks/*.txt text eol=lf` to `.gitattributes`.
6. **B5 Remove:** replace "runs `uv cache prune`" by "runs `uv cache clean` when no pack remains, and offers 'Free up space' in Settings otherwise" (prune frees nothing; clean costs a re-download on the next install).
7. **B5 hosts, C2 table, Appendix 4:** add `download-r2.pytorch.org` (already added to the owner's Claude cloud environment during this spike, with approval); spell PyPI as `pypi.org` + `files.pythonhosted.org`. If Python downloads are ever enabled, pin `UV_PYTHON_INSTALL_MIRROR` to GitHub rather than adding `releases.astral.sh`.
8. **B5 new rule:** re-point packs when the bundled Python's path changes (3.9), and on Windows refuse pack folder paths longer than 150 characters; pack folder names ≤ 40 characters.
9. **B5 Python-version sentence:** "A pack may declare another Python version" works (3.10) but is not needed for MVP; suggest T03.5 leaves it out and B5 says "not implemented until a pack needs it".
10. **T03.5:** `make_locks.py --check`; free-disk figure from a measured install (4.6); the "killed midway" acceptance test should also cover a pack whose install succeeded but whose step 4 fails (the long-path case); unit tests with the fake `uv` should assert the environment in 4.1; smoke packs pin `torch==2.14.1` with backends `cpu`/`cu126`.
11. **Settings task (storage folder):** follow 3.9 — move cache, rebuild packs offline, never move pack folders across volumes.
12. **Model-install UI for GPU packs:** mention that NVIDIA's CUDA libraries are downloaded under NVIDIA's licence (3.11) — needs an owner decision.
13. **CI:** PowerShell 5.1 treats redirected stderr of native tools as an error (`setup.ps1 > log 2>&1` failed in run 1); keep that in mind for the weekly slow-install job.

## 7. Not covered

GPU execution (no GPU on any machine); authenticated proxies; a real corporate CA in the Windows store; third-party antivirus products; network drives, exFAT/FAT32 or ReFS storage folders (expected to behave like the cross-volume case, i.e. full copies, if hard links are unsupported — not measured); macOS; AppImage mount behaviour; Windows download sizes; the exact Windows path-length limit between 161 and 202 characters.
