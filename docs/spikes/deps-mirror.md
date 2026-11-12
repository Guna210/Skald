# Mirroring pinned build dependencies (`deps-v1`)

> **Do this by 25 November 2026:** the upstream `ffmpeg` download links disappear around 26 November.

## Why this mirror exists

Skald's build and setup scripts download pinned binaries (`ffmpeg`, `uv`, and standalone CPython 3.12) listed in `scripts/deps.lock.json`. Upstream `FFmpeg-Builds` deletes older dated autobuild releases after ~14 days, which would break reproducible builds and remove the corresponding source context.

Hosting all **6** binary archives plus the **2** FFmpeg source snapshots on a `deps-v1` GitHub Release in this repository ensures `scripts/fetch_deps.py` can always download the exact SHA-256–verified files (`mirror_url` first, falling back to upstream `url` if needed) and keeps the LGPL-3.0 source available.

---

## Step 1 — Download all 8 exact files

Download each of the **8** files from its **Source URL** below into a temporary folder on your computer.

> **Important:** Do **not** unpack, extract, or rename any of the 8 downloaded files. Upload the archives exactly as downloaded.

### 6 binary archives (used by `scripts/fetch_deps.py`)

| Tool | Platform | Exact filename | Source URL | Expected SHA-256 |
|---|---|---|---|---|
| `ffmpeg` | `win64` | `ffmpeg-n9.0.2-57-gd838f9f9ae-win64-lgpl-9.0.zip` | https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/download/autobuild-2026-11-12-15-40/ffmpeg-n9.0.2-57-gd838f9f9ae-win64-lgpl-9.0.zip | `7a7d4b2adafe4b2de2a0fe0077a37e3d1dae43de28df38538ca79bc5d861e33e` |
| `ffmpeg` | `linux64` | `ffmpeg-n9.0.2-57-gd838f9f9ae-linux64-lgpl-9.0.tar.xz` | https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/download/autobuild-2026-11-12-15-40/ffmpeg-n9.0.2-57-gd838f9f9ae-linux64-lgpl-9.0.tar.xz | `416081d93cb6cdcac9fade4f76d94321964253860b85b80404b5b9fb38dc3499` |
| `uv` | `win64` | `uv-x86_64-pc-windows-msvc.zip` | https://github.com/astral-sh/uv/releases/download/0.13.8/uv-x86_64-pc-windows-msvc.zip | `529e78a9cec6cd7e3e014f7ecd8bda0c113969d4ed0f2efeedb85c30943325b8` |
| `uv` | `linux64` | `uv-x86_64-unknown-linux-gnu.tar.gz` | https://github.com/astral-sh/uv/releases/download/0.13.8/uv-x86_64-unknown-linux-gnu.tar.gz | `5acfd9177cfecf0bf87578f059728215ccc884388988f55f7a65041b57387d91` |
| `python` | `win64` | `cpython-3.12.16+20261110-x86_64-pc-windows-msvc-install_only_stripped.tar.gz` | https://github.com/astral-sh/python-build-standalone/releases/download/20261110/cpython-3.12.16%2B20261110-x86_64-pc-windows-msvc-install_only_stripped.tar.gz | `355ee61b8207b91574491b1c6dc9b0ebb4408fc56bfafe498f3ef439314b52dc` |
| `python` | `linux64` | `cpython-3.12.16+20261110-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz` | https://github.com/astral-sh/python-build-standalone/releases/download/20261110/cpython-3.12.16%2B20261110-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz | `6a9e62dad033790aef722dbd370e0ce76ce17b73627ba3ae679f537049350b39` |

### 2 FFmpeg source snapshots (LGPL-3.0 compliance; not in `deps.lock.json`)

| Snapshot | Exact filename | Source URL | Size (bytes) | Expected SHA-256 |
|---|---|---|---|---|
| FFmpeg `release/9.0` source | `FFmpeg-d838f9f9aeb0e09b4d068e2af20a46a12640696f.tar.gz` | https://github.com/FFmpeg/FFmpeg/archive/d838f9f9aeb0e09b4d068e2af20a46a12640696f.tar.gz | `17330939` | `479396204090c378cc2d181fef5355a1da64c5903e29a7fda687960101e70df9` |
| FFmpeg-Builds scripts | `FFmpeg-Builds-c9fe5114060e507409f7ee07edfd82efaf25d767.tar.gz` | https://github.com/FFmpeg-Builds/FFmpeg-Builds/archive/c9fe5114060e507409f7ee07edfd82efaf25d767.tar.gz | `119598` | `fb708487f587ffbf6c80c8d34fe0f96f7da8a1f88b8b6b5d1b27d91715fa2595` |

### Optional: verify SHA-256 checksums before uploading

Inside the folder where you saved the 8 files, verify every hash matches the tables above:

- **Windows (PowerShell):**
  ```powershell
  Get-ChildItem | Get-FileHash -Algorithm SHA256 | Format-Table Hash, @{N="File";E={$_.Path | Split-Path -Leaf}} -AutoSize
  ```
- **Linux / macOS (bash):**
  ```bash
  sha256sum *
  ```

---

## Step 2 — Create and publish release `deps-v1` on GitHub

1. Open **https://github.com/Guna210/Skald/releases/new** in your browser (signed in as `Guna210`).
2. Click **Choose a tag**, type **`deps-v1`**, and click **Create new tag: deps-v1 on publish**.
3. Keep **Target** set to **`master`**.
4. Set **Release title** to **`Pinned build dependencies (v1)`**.
5. Copy the entire block below and paste it into the **Describe this release** box:

````markdown
These are unmodified upstream archives, mirrored for reproducible builds.

### FFmpeg (`n9.0.2-57-gd838f9f9ae`, `win64` & `linux64` `lgpl-9.0` builds)
- **License:** `LGPL-3.0-or-later` (configured with `--enable-version3`)
- **FFmpeg source (`release/9.0`):** https://github.com/FFmpeg/FFmpeg/commit/d838f9f9aeb0e09b4d068e2af20a46a12640696f (commit `d838f9f9aeb0e09b4d068e2af20a46a12640696f`)
- **Build scripts (`FFmpeg-Builds`):** https://github.com/FFmpeg-Builds/FFmpeg-Builds/commit/c9fe5114060e507409f7ee07edfd82efaf25d767 (commit `c9fe5114060e507409f7ee07edfd82efaf25d767`, behind `autobuild-2026-11-12-15-40`)
- The bundled third-party libraries and their exact source versions are defined by those build scripts. Both source snapshots (`FFmpeg-d838f9f9aeb0e09b4d068e2af20a46a12640696f.tar.gz` and `FFmpeg-Builds-c9fe5114060e507409f7ee07edfd82efaf25d767.tar.gz`) are attached to this release.

### uv (`0.13.8`, `win64` & `linux64`)
- **License:** `MIT OR Apache-2.0`
- **Source:** https://github.com/astral-sh/uv/tree/0.13.8 (commit `3d97a6aad5ad989c1b4fc89406d54f0dce370b72`)
- **Apache-2.0 license:** https://github.com/astral-sh/uv/blob/0.13.8/LICENSE-APACHE
- **MIT license (`LICENSE-MIT` at `0.13.8`):**

```
MIT License

Copyright (c) 2025 Astral Software Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### CPython `3.12.16` via `python-build-standalone` (`20261110`, `win64` & `linux64`)
- **License:** `PSF-2.0` plus bundled components' licences
- **Build scripts source:** https://github.com/astral-sh/python-build-standalone/tree/20261110 (commit `9244801782b78e4c4afc5c82a4524aa2101d3298`)
- **CPython source:** https://github.com/python/cpython/tree/v3.12.16
````

6. Drag and drop all **8** downloaded files (the 6 binary archives and the 2 FFmpeg source snapshots) into the **Attach binaries by dropping them here or selecting them** area at the bottom.
7. Wait for all 8 upload progress bars to finish, then check **every** uploaded filename against the **Exact filename** columns above — especially check that the `+` in `cpython-3.12.16+20261110-...` was preserved. **If GitHub changed any file name (for example, turning `+` into `.` or a space), delete that asset, stop, and tell the Orchestrator.**
8. Click the green **Publish release** button. Do **not** click *Save draft* (draft releases are private and return 404 to `fetch_deps.py`).

---

## Step 3 — Test the CPython `%2B` mirror URL in your browser

Click this link after publishing:

- https://github.com/Guna210/Skald/releases/download/deps-v1/cpython-3.12.16%2B20261110-x86_64-pc-windows-msvc-install_only_stripped.tar.gz

Confirm your browser starts downloading `cpython-3.12.16+20261110-x86_64-pc-windows-msvc-install_only_stripped.tar.gz` instead of showing a GitHub **404** page.

---

## Step 4 — Confirm `fetch_deps.py` uses the mirror

In your local Skald repo checkout (after running the setup script so `core/.venv` exists), delete (or move aside) the `vendor/` folder and run `fetch_deps.py` with the project venv Python:

- **Windows (PowerShell):**
  ```powershell
  Remove-Item -Recurse -Force vendor -ErrorAction SilentlyContinue
  core\.venv\Scripts\python scripts\fetch_deps.py
  ```
- **Linux (bash):**
  ```bash
  rm -rf vendor
  core/.venv/bin/python scripts/fetch_deps.py
  ```

Confirm the output prints **`using mirror: https://github.com/Guna210/Skald/releases/download/deps-v1/...`** for `ffmpeg`, `uv`, and `python` (with no `falling back to source` messages), followed by their `--version` / `-version` outputs.
