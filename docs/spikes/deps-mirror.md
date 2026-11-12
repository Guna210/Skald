# Mirroring pinned build dependencies (`deps-v1`)

## Why this mirror exists

Skald's build and setup scripts download pinned binaries (`ffmpeg`, `uv`, and standalone CPython 3.12) listed in `scripts/deps.lock.json`. Upstream `FFmpeg-Builds` deletes older dated autobuild releases after a retention window, which would break reproducible builds later.

Hosting a copy of all 6 pinned archives on a `deps-v1` GitHub Release in this repository ensures `scripts/fetch_deps.py` can always download the exact SHA-256–verified files (`mirror_url` first, falling back to upstream `url` if the mirror is unavailable).

---

## Step 1 — Download all 6 exact files

Download each file from its **Source URL** below into a temporary folder on your computer.

> **Important:** Do **not** unpack, extract, or rename any of the 6 downloaded files. Upload the archives exactly as downloaded.

| Tool | Platform | Exact filename | Source URL | Expected SHA-256 |
|---|---|---|---|---|
| `ffmpeg` | `win64` | `ffmpeg-n9.0.2-57-gd838f9f9ae-win64-lgpl-9.0.zip` | https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/download/autobuild-2026-11-12-15-40/ffmpeg-n9.0.2-57-gd838f9f9ae-win64-lgpl-9.0.zip | `7a7d4b2adafe4b2de2a0fe0077a37e3d1dae43de28df38538ca79bc5d861e33e` |
| `ffmpeg` | `linux64` | `ffmpeg-n9.0.2-57-gd838f9f9ae-linux64-lgpl-9.0.tar.xz` | https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/download/autobuild-2026-11-12-15-40/ffmpeg-n9.0.2-57-gd838f9f9ae-linux64-lgpl-9.0.tar.xz | `416081d93cb6cdcac9fade4f76d94321964253860b85b80404b5b9fb38dc3499` |
| `uv` | `win64` | `uv-x86_64-pc-windows-msvc.zip` | https://github.com/astral-sh/uv/releases/download/0.13.8/uv-x86_64-pc-windows-msvc.zip | `529e78a9cec6cd7e3e014f7ecd8bda0c113969d4ed0f2efeedb85c30943325b8` |
| `uv` | `linux64` | `uv-x86_64-unknown-linux-gnu.tar.gz` | https://github.com/astral-sh/uv/releases/download/0.13.8/uv-x86_64-unknown-linux-gnu.tar.gz | `5acfd9177cfecf0bf87578f059728215ccc884388988f55f7a65041b57387d91` |
| `python` | `win64` | `cpython-3.12.16+20261110-x86_64-pc-windows-msvc-install_only_stripped.tar.gz` | https://github.com/astral-sh/python-build-standalone/releases/download/20261110/cpython-3.12.16%2B20261110-x86_64-pc-windows-msvc-install_only_stripped.tar.gz | `355ee61b8207b91574491b1c6dc9b0ebb4408fc56bfafe498f3ef439314b52dc` |
| `python` | `linux64` | `cpython-3.12.16+20261110-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz` | https://github.com/astral-sh/python-build-standalone/releases/download/20261110/cpython-3.12.16%2B20261110-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz | `6a9e62dad033790aef722dbd370e0ce76ce17b73627ba3ae679f537049350b39` |

### Optional: verify SHA-256 checksums before uploading

Inside the folder where you saved the 6 files, you can verify every hash matches the table above:

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
5. Drag and drop all **6** downloaded files into the **Attach binaries by dropping them here or selecting them** area at the bottom.
6. Wait for all 6 upload progress bars to finish, then check each uploaded filename in the list against the **Exact filename** column above — especially check that the `+` in `cpython-3.12.16+20261110-...` was preserved (not changed to a space or `.`).
7. Click the green **Publish release** button. Do **not** click *Save draft* (draft releases are private and return 404 to `fetch_deps.py`).

---

## Step 3 — Test one mirror URL in your browser

Click this link after publishing:

- https://github.com/Guna210/Skald/releases/download/deps-v1/uv-x86_64-pc-windows-msvc.zip

Confirm your browser starts downloading `uv-x86_64-pc-windows-msvc.zip` instead of showing a GitHub **404** page.

---

## Step 4 — Confirm `fetch_deps.py` uses the mirror

In your local Skald repo checkout, delete (or move aside) the `vendor/` folder and run `fetch_deps.py`:

- **Windows (PowerShell):**
  ```powershell
  Remove-Item -Recurse -Force vendor -ErrorAction SilentlyContinue
  python scripts\fetch_deps.py
  ```
- **Linux (bash):**
  ```bash
  rm -rf vendor
  python3 scripts/fetch_deps.py
  ```

Confirm the output prints **`using mirror: https://github.com/Guna210/Skald/releases/download/deps-v1/...`** for `ffmpeg`, `uv`, and `python` (with no `falling back to source` messages), followed by their `--version` / `-version` outputs.
