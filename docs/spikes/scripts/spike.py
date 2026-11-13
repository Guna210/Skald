"""Spike T03.4: engine-pack measurements (throwaway; the real code is T03.5's packs/manager.py).

Standard library only. Run it with the dev venv Python after scripts/setup.* has filled vendor/:

  python spike.py lock [--check]     regenerate (or verify) the sample locks for Linux and Windows
  python spike.py measure --work DIR [--packs cpu,cu12] [--other-volume DIR] [--only STEP,...]

`measure` writes DIR/results.json (merged across runs) and prints it. Findings: docs/spikes/engine-packs.md.
"""

import argparse
import base64
import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
IS_WIN = os.name == "nt"
PLAT = "win64" if IS_WIN else "linux64"
OS_NAME = "windows" if IS_WIN else "linux"
DEPS = json.loads((REPO / "scripts" / "deps.lock.json").read_text())
UV = str(REPO / "vendor" / "uv" / PLAT / DEPS["uv"]["assets"][PLAT]["bin"])
PY = REPO / "vendor" / "python" / PLAT / DEPS["python"]["assets"][PLAT]["bin"]

# kind -> (family, accel used in names, uv --torch-backend)
PACKS = {"cpu": ("torch-cpu", "cpu", "cpu"), "cu12": ("torch-cu12", "cu12", "cu126")}
UV_PLATFORMS = {"linux": "x86_64-manylinux_2_28", "windows": "x86_64-pc-windows-msvc"}
# Fixed so regenerating gives the same lock on any machine and day.
EXCLUDE_NEWER = "2026-11-13T00:00:00Z"
COMPILE_COMMAND = "python docs/spikes/scripts/spike.py lock"


def lock_path(kind, os_name=OS_NAME):
    family, accel, _ = PACKS[kind]
    return HERE / family / "locks" / f"{os_name}-{accel}.txt"


def compile_cmd(kind, os_name, out, python_version="3.12"):
    family, _, backend = PACKS[kind]
    return [
        UV, "pip", "compile", str(HERE / family / "requirements.in"),
        "--generate-hashes", "--only-binary", ":all:",
        "--python-version", python_version, "--python-platform", UV_PLATFORMS[os_name],
        "--torch-backend", backend, "--exclude-newer", EXCLUDE_NEWER,
        "--emit-index-annotation", "--custom-compile-command", COMPILE_COMMAND,
        "-q", "-o", str(out),
    ]  # fmt: skip


def base_env(work=None):
    """The environment every uv call runs in: nothing inherited from the user's uv settings."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("UV_")}
    env.update(UV_NO_CONFIG="1", UV_NO_PROGRESS="1", UV_PYTHON_DOWNLOADS="never", UV_LINK_MODE="hardlink")
    env.update(UV_SYSTEM_CERTS="1")  # trust the OS certificate store (corporate proxies); see step_tls
    if work:
        env.update(UV_CACHE_DIR=str(work / "uv-cache"), UV_PYTHON_INSTALL_DIR=str(work / "python"))
    return env


def run(cmd, env, ok=True):
    """Run a command; return (seconds, returncode, combined output)."""
    cmd = [str(c) for c in cmd]
    print("+", " ".join(cmd), flush=True)
    t0 = time.perf_counter()
    p = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    secs = round(time.perf_counter() - t0, 2)
    print(p.stdout[-3000:], f"[{secs}s rc={p.returncode}]", flush=True)
    if ok and p.returncode != 0:
        sys.exit(f"command failed: {cmd}")
    return secs, p.returncode, p.stdout


def tail(out, n=6):
    return [line for line in out.strip().splitlines() if line.strip()][-n:]


def lp(path):
    """Windows: the \\\\?\\ prefix lets os.walk/stat/rmtree handle paths over 260 characters."""
    return "\\\\?\\" + os.path.abspath(path) if IS_WIN else str(path)


def usage(*roots):
    """(bytes, files) under the roots, counting each hard-linked file once."""
    seen, total = set(), 0
    for root in roots:
        for d, _, files in os.walk(lp(root)):
            for f in files:
                st = os.lstat(os.path.join(d, f))
                if (st.st_dev, st.st_ino) not in seen:
                    seen.add((st.st_dev, st.st_ino))
                    total += st.st_size
    return total, len(seen)


def mb(n):
    return round(n / 1e6, 1)


def free(path):
    return shutil.disk_usage(path).free


def rm(path):
    def writable(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)

    if os.path.exists(lp(path)):
        shutil.rmtree(lp(path), onexc=writable)


def longest_paths(pack, n=3):
    root = lp(pack)
    rels = [os.path.relpath(os.path.join(d, f), root) for d, _, files in os.walk(root) for f in files]
    rels.sort(key=len, reverse=True)
    return [{"len": len(r), "path": r} for r in rels[:n]]


def biggest_file(pack):
    root = lp(pack)
    files = [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs]
    path = max(files, key=lambda p: os.lstat(p).st_size)
    st = os.lstat(path)
    return {"path": os.path.relpath(path, root), "mb": mb(st.st_size), "nlink": st.st_nlink}


def lock_hashes(lock):
    raw = lock.read_bytes()
    return {
        "sha256_raw_8": hashlib.sha256(raw).hexdigest()[:8],
        "sha256_lf_8": hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()[:8],
        "has_crlf": b"\r\n" in raw,
    }


def pack_python(pack):
    return Path(pack) / ("Scripts/python.exe" if IS_WIN else "bin/python")


def make_dummy_wheel(folder):
    """A tiny local wheel standing in for the bundled skald_worker wheel (B5 step 3)."""
    name, version = "skald_spike_dummy", "0.0.1"
    info = f"{name}-{version}.dist-info"
    files = {
        f"{name}/__init__.py": f'VERSION = "{version}"\n',
        f"{info}/METADATA": f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        f"{info}/WHEEL": "Wheel-Version: 1.0\nGenerator: spike\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record = ""
    for path, text in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(text.encode()).digest()).rstrip(b"=").decode()
        record += f"{path},sha256={digest},{len(text.encode())}\n"
    files[f"{info}/RECORD"] = record + f"{info}/RECORD,,\n"
    wheel = Path(folder) / f"{name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as z:
        for path, text in files.items():
            z.writestr(path, text)
    return wheel


class Ctx:
    def __init__(self, work, other):
        self.work, self.other = work, other
        self.packs = work / "packs"
        self.packs.mkdir(parents=True, exist_ok=True)
        self.env = base_env(work)
        self.wheel = make_dummy_wheel(work)
        self.results_file = work / "results.json"
        self.results = json.loads(self.results_file.read_text()) if self.results_file.exists() else {}

    def save(self, key, value):
        self.results[key] = value
        self.results_file.write_text(json.dumps(self.results, indent=2))

    def name(self, kind, suffix=""):
        family, accel, _ = PACKS[kind]
        return f"{family}-{OS_NAME}-{accel}-{lock_hashes(lock_path(kind))['sha256_lf_8']}{suffix}"

    def install(self, kind, pack, env=None, python=PY, venv_args=(), lock=None):
        """B5 steps 1-2. Returns (venv seconds, sync seconds, sync output)."""
        env = env or self.env
        t_venv, _, _ = run([UV, "venv", "--python", python, "--no-project", *venv_args, pack], env)
        t_sync, _, out = run(
            [UV, "pip", "sync", "--python", pack_python(pack), "--require-hashes", "--no-build",
             "--torch-backend", PACKS[kind][2], lock or lock_path(kind)],
            env,
        )  # fmt: skip
        return t_venv, t_sync, out

    def check(self, pack, ok=True):
        secs, rc, out = run([pack_python(pack), HERE / "check_pack.py"], self.env, ok=ok)
        return json.loads(out.strip().splitlines()[-1]) if rc == 0 else {"failed": tail(out, 4)}


# --- steps -----------------------------------------------------------------


def step_cold(ctx, kind):
    """Cold cache: B5 steps 1-4 for the first pack."""
    if (ctx.work / "uv-cache").exists() and kind == "cpu":
        sys.exit("cold step needs an empty --work folder")
    pack = ctx.packs / ctx.name(kind)
    cache_before = usage(ctx.work / "uv-cache")[0]
    free0 = free(ctx.work)
    t_venv, t_sync, out = ctx.install(kind, pack)
    delta = free0 - free(ctx.work)
    t_wheel, _, _ = run(
        [UV, "pip", "install", "--python", pack_python(pack), "--offline", "--no-index", "--no-deps", ctx.wheel],
        ctx.env,
    )
    first = ctx.check(pack)
    second = ctx.check(pack)
    pack_bytes, pack_files = usage(pack)
    ctx.save(f"cold_{kind}", {
        "pack": pack.name, "lock": lock_hashes(lock_path(kind)),
        "venv_s": t_venv, "sync_s": t_sync, "sync_output": tail(out, 4),
        "dummy_wheel_offline_s": t_wheel, "check": first, "second_import_s": second["import_s"],
        "free_space_delta_mb": mb(delta), "pack_mb": mb(pack_bytes), "pack_files": pack_files,
        "cache_added_mb": mb(usage(ctx.work / "uv-cache")[0] - cache_before),
        "pack_plus_cache_unique_mb": mb(usage(pack, ctx.work / "uv-cache")[0]),
        "biggest_file": biggest_file(pack), "longest_paths": longest_paths(pack),
    })  # fmt: skip


def step_warm(ctx, kind):
    """Warm cache: a second pack from the same lock; this is the hard-link deduplication measurement."""
    a, b = ctx.packs / ctx.name(kind), ctx.packs / ctx.name(kind, "-b")
    free0 = free(ctx.work)
    t_venv, t_sync, out = ctx.install(kind, b)
    delta = free0 - free(ctx.work)
    ctx.save(f"warm_{kind}", {
        "venv_s": t_venv, "sync_s": t_sync, "sync_output": tail(out, 3),
        "free_space_delta_mb": mb(delta), "second_pack_alone_mb": mb(usage(b)[0]),
        "both_packs_unique_mb": mb(usage(a, b)[0]),
        "both_packs_plus_cache_unique_mb": mb(usage(a, b, ctx.work / "uv-cache")[0]),
        "biggest_file_in_first_pack": biggest_file(a),
    })  # fmt: skip


def step_bytecode(ctx, kind):
    """Precompile the second pack: time, extra size, and its effect on the longest path."""
    b = ctx.packs / ctx.name(kind, "-b")
    before = usage(b)[0]
    secs, rc, out = run([pack_python(b), "-m", "compileall", "-q", b], ctx.env, ok=False)
    ctx.save(f"bytecode_{kind}", {
        "compileall_s": secs, "rc": rc, "errors": tail(out, 3) if rc else [],
        "added_mb": mb(usage(b)[0] - before),
        "longest_paths": longest_paths(b), "import_s_after": ctx.check(b)["import_s"],
    })  # fmt: skip


def entry_point(pack):
    """Run a console script (numpy's f2py) to see whether entry points survive."""
    exe = Path(pack) / ("Scripts/f2py.exe" if IS_WIN else "bin/f2py")
    try:
        secs, rc, out = run([exe, "-v"], base_env(), ok=False)
    except OSError as e:
        return f"failed: {e}"
    return "ok" if rc == 0 else f"failed: {tail(out, 2)}"


def step_move(ctx, kind):
    """Storage-folder change: does a moved pack work? Plain venv, --relocatable venv, and a moved base Python."""
    r = {}
    b = ctx.packs / ctx.name(kind, "-b")
    r["entry_point_before_move"] = entry_point(b)
    moved = ctx.work / "moved" / b.name
    moved.parent.mkdir(exist_ok=True)
    b.rename(moved)
    r["plain_venv_moved"] = {"check": ctx.check(moved, ok=False), "entry_point": entry_point(moved)}

    c = ctx.packs / ctx.name(kind, "-c")
    t_venv, t_sync, _ = ctx.install(kind, c, venv_args=["--relocatable"])
    moved_c = ctx.work / "moved" / c.name
    c.rename(moved_c)
    r["relocatable_venv_moved"] = {"check": ctx.check(moved_c, ok=False), "entry_point": entry_point(moved_c)}
    r["pyvenv_cfg_relocatable"] = (moved_c / "pyvenv.cfg").read_text().splitlines()

    # The base interpreter moves (app reinstalled elsewhere; an AppImage mounts at a new path on every start).
    base1, base2 = ctx.work / "pybase1", ctx.work / "pybase2"
    shutil.copytree(PY.parents[0 if IS_WIN else 1], base1, symlinks=True)
    d = ctx.packs / "basemove"
    run([UV, "venv", "--python", base1 / PY.relative_to(PY.parents[0 if IS_WIN else 1]), "--no-project", d], ctx.env)
    run([UV, "pip", "install", "--python", pack_python(d), "--offline", "--no-index", ctx.wheel], ctx.env)
    probe = [pack_python(d), "-c", "import skald_spike_dummy, sys; print('ok', sys.base_prefix)"]
    r["base_python_before"] = tail(run(probe, ctx.env)[2], 1)
    base1.rename(base2)
    try:
        r["base_python_moved"] = tail(run(probe, ctx.env, ok=False)[2], 2)
    except OSError as e:
        r["base_python_moved"] = [f"failed: {e}"]
    new_python = base2 / PY.relative_to(PY.parents[0 if IS_WIN else 1])
    t, rc, out = run([UV, "venv", "--python", new_python, "--no-project", "--allow-existing", d], ctx.env, ok=False)
    r["rehome_with_allow_existing"] = {"s": t, "rc": rc, "after": tail(run(probe, ctx.env, ok=False)[2], 2)}
    for p in (ctx.work / "moved", base2, d):
        rm(p)
    ctx.save(f"move_{kind}", r)


def step_deep(ctx, kind):
    """Windows long paths: install a pack under a root deep enough that files pass 260 characters."""
    root = ctx.work
    while len(str(root)) < 190:
        root = root / ("d" * 40)
    pack = root / ctx.name(kind)
    pack.parent.mkdir(parents=True, exist_ok=True)
    r = {"pack_root_len": len(str(pack))}
    t_venv, rc, out = run([UV, "venv", "--python", PY, "--no-project", pack], ctx.env, ok=False)
    if rc == 0:
        t_sync, rc, out = run(
            [UV, "pip", "sync", "--python", pack_python(pack), "--require-hashes", "--no-build",
             "--torch-backend", PACKS[kind][2], lock_path(kind)],
            ctx.env, ok=False,
        )  # fmt: skip
    r["install_rc"] = rc
    r["install_output"] = tail(out, 5)
    if rc == 0:
        r["longest_full_path"] = len(str(pack)) + 1 + longest_paths(pack, 1)[0]["len"]
        r["check"] = ctx.check(pack, ok=False)
    rm(ctx.work / ("d" * 40))
    ctx.save(f"deep_{kind}{os.environ.get('SPIKE_LABEL', '')}", r)


def step_tamper(ctx, kind):
    """--require-hashes must reject a lock whose hashes do not match the files (warm cache and cold cache)."""
    bad = ctx.work / "tampered.txt"
    flip = str.maketrans("0123456789abcdef", "123456789abcdef0")
    lines = lock_path(kind).read_text().splitlines()
    bad.write_text("\n".join(ln[:-9] + ln[-9:].translate(flip) if "--hash=" in ln else ln for ln in lines) + "\n")
    r = {}
    for label, cache in (("warm_cache", ctx.work / "uv-cache"), ("cold_cache", ctx.work / "uv-cache-tamper")):
        pack = ctx.packs / "tampered"
        env = dict(ctx.env, UV_CACHE_DIR=str(cache))
        run([UV, "venv", "--python", PY, "--no-project", pack], env)
        secs, rc, out = run(
            [UV, "pip", "sync", "--python", pack_python(pack), "--require-hashes", "--no-build",
             "--torch-backend", PACKS[kind][2], bad],
            env, ok=False,
        )  # fmt: skip
        r[label] = {"rc": rc, "s": secs, "output": tail(out, 8), "files_installed": usage(pack)[1]}
        rm(pack)
    rm(ctx.work / "uv-cache-tamper")
    ctx.save("tamper", r)


def step_relocate(ctx, kind):
    """Storage-folder change, recommended way: copy the uv cache to the new volume, then rebuild packs offline."""
    if not ctx.other or os.stat(ctx.other).st_dev == os.stat(ctx.work).st_dev:
        ctx.save("relocate", {"skipped": "no --other-volume on a different volume"})
        return
    new_cache, pack = ctx.other / "uv-cache", ctx.other / "packs" / ctx.name(kind)
    t0 = time.perf_counter()
    shutil.copytree(lp(ctx.work / "uv-cache"), lp(new_cache), symlinks=True)
    copy_s = round(time.perf_counter() - t0, 2)
    env = dict(ctx.env, UV_CACHE_DIR=str(new_cache), UV_OFFLINE="1")
    free0 = free(ctx.other)
    t_venv, t_sync, out = ctx.install(kind, pack, env=env)
    ctx.save("relocate", {
        "cache_copy_s": copy_s, "cache_mb": mb(usage(new_cache)[0]),
        "offline_rebuild_s": round(t_venv + t_sync, 2), "sync_output": tail(out, 2),
        "rebuild_free_space_delta_mb": mb(free0 - free(ctx.other)),
        "biggest_file": biggest_file(pack), "check": ctx.check(pack, ok=False),
    })  # fmt: skip
    rm(ctx.other / "packs")
    rm(new_cache)


def step_prune(ctx, kind):
    """Remove = delete the pack, then `uv cache prune`. Does prune free the removed packs' wheels?"""
    cache, pack = ctx.work / "uv-cache", ctx.packs / ctx.name(kind)
    cache_only = lambda: usage(pack, cache)[0] - usage(pack)[0]  # noqa: E731  bytes no pack links to
    before, only_before, free0 = usage(cache), cache_only(), free(ctx.work)
    secs, _, out = run([UV, "cache", "prune"], ctx.env)
    after = usage(cache)
    ctx.save("prune", {
        "prune_s": secs, "output": tail(out, 2), "cache_mb_before": mb(before[0]), "cache_mb_after": mb(after[0]),
        "cache_not_linked_from_a_pack_mb_before": mb(only_before), "cache_not_linked_from_a_pack_mb_after": mb(cache_only()),
        "free_space_gained_mb": mb(free(ctx.work) - free0),
    })  # fmt: skip


def step_xvol(ctx, kind):
    """Cache on another volume: hard links cannot work; what does uv do and what does it cost?"""
    if not ctx.other or os.stat(ctx.other).st_dev == os.stat(ctx.work).st_dev:
        ctx.save("xvol", {"skipped": "no --other-volume on a different volume"})
        return
    env = dict(ctx.env, UV_CACHE_DIR=str(ctx.other / "uv-cache"))
    e, f = ctx.packs / ctx.name(kind, "-x"), ctx.packs / ctx.name(kind, "-y")
    free_w, free_o = free(ctx.work), free(ctx.other)
    t_venv, t_sync, out = ctx.install(kind, e, env=env)
    r = {
        "cold_sync_s": t_sync, "sync_output": tail(out, 6),
        "packs_volume_delta_mb": mb(free_w - free(ctx.work)), "cache_volume_delta_mb": mb(free_o - free(ctx.other)),
        "biggest_file": biggest_file(e),
    }  # fmt: skip
    free_w = free(ctx.work)
    t_venv, t_sync, out = ctx.install(kind, f, env=env)
    r.update(second_pack_sync_s=t_sync, second_pack_delta_mb=mb(free_w - free(ctx.work)), second_output=tail(out, 4))
    for p in (e, f, ctx.other / "uv-cache"):
        rm(p)
    ctx.save("xvol", r)


def step_py311(ctx, kind, env=None, key="py311"):
    """A pack that needs Python 3.11: uv downloads a managed Python into UV_PYTHON_INSTALL_DIR."""
    env = dict(env or ctx.env)
    pydir = Path(env["UV_PYTHON_INSTALL_DIR"])
    pack = ctx.packs / (ctx.name(kind, "-py311") + ("" if key == "py311" else "-p"))
    r = {}
    _, rc, out = run([UV, "venv", "--python", "3.11", "--managed-python", "--no-project", pack], env, ok=False)
    r["downloads_never"] = {"rc": rc, "output": tail(out, 3)}
    rm(pack)
    env["UV_PYTHON_DOWNLOADS"] = "automatic"
    _, _, out = run([UV, "python", "list", "3.11", "--managed-python", "--only-downloads", "--show-urls"], env)
    url = next(ln.split()[1] for ln in out.splitlines() if ln.startswith("cpython-3.11"))
    r["download_url"] = url
    # Is the download verified? Serve a different (valid) archive under the same name from a file:// mirror.
    build, fname = url.rsplit("/", 2)[1:]
    mirror = ctx.work / "badmirror"
    (mirror / build).mkdir(parents=True, exist_ok=True)
    with tarfile.open(mirror / build / fname.replace("%2B", "+"), "w:gz") as tar:
        tar.add(HERE / "check_pack.py", arcname="python/bin/python")
    shutil.copy(mirror / build / fname.replace("%2B", "+"), mirror / build / fname)
    bad_env = dict(env, UV_PYTHON_INSTALL_MIRROR=mirror.as_uri(), UV_PYTHON_INSTALL_DIR=str(ctx.work / "python-bad"))
    _, rc, out = run([UV, "venv", "--python", "3.11", "--managed-python", "--no-project", pack], bad_env, ok=False)
    r["tampered_mirror"] = {"rc": rc, "output": tail(out, 4)}
    for p in (pack, mirror, ctx.work / "python-bad"):
        rm(p)
    free0 = free(ctx.work)
    t_venv, _, out = run([UV, "venv", "-v", "--python", "3.11", "--managed-python", "--no-project", pack], env)
    r["venv_with_download_s"] = t_venv
    r["log_lines"] = [ln for ln in out.splitlines() if "http" in ln or "ownload" in ln or "sha256" in ln.lower()][:12]
    r["install_dir_entries"] = sorted(os.listdir(pydir))
    r["install_dir_mb"] = mb(usage(pydir)[0])
    r["free_space_delta_mb"] = mb(free0 - free(ctx.work))
    r["pyvenv_cfg"] = (pack / "pyvenv.cfg").read_text().splitlines()
    lock311 = ctx.work / "lock-py311.txt"
    run(compile_cmd(kind, OS_NAME, lock311, "3.11"), env)
    lines = lambda p: {ln for ln in p.read_text().splitlines() if "==" in ln}  # noqa: E731
    r["pins_differing_from_py312_lock"] = sorted(lines(lock311) ^ lines(lock_path(kind)))
    t_venv, t_sync, out = ctx.install(kind, pack, env=env, python="3.11", venv_args=["--managed-python", "--allow-existing"], lock=lock311)
    r["sync_s"] = t_sync
    r["check"] = ctx.check(pack)
    rm(pack)
    ctx.save(key, r)


def step_proxy(ctx, kind):
    """Behind HTTPS_PROXY (a plain CONNECT proxy, no TLS interception): does it work, and which hosts are used?"""
    if os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"):
        ctx.save("proxy", {"skipped": "this machine is already behind a proxy; see the tls step"})
        return
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    log = ctx.work / "proxy.log"
    log.write_text("")
    proxy = subprocess.Popen([sys.executable, str(HERE / "connect_proxy.py"), str(port), str(log)])
    try:
        time.sleep(1)
        env = dict(ctx.env, HTTPS_PROXY=f"http://127.0.0.1:{port}", UV_CACHE_DIR=str(ctx.work / "uv-cache-proxy"),
                   UV_PYTHON_INSTALL_DIR=str(ctx.work / "python-proxy"))  # fmt: skip
        pack = ctx.packs / ctx.name(kind, "-p")
        t_venv, t_sync, out = ctx.install(kind, pack, env=env)
        r = {"cold_sync_s": t_sync, "sync_output": tail(out, 3), "check": ctx.check(pack)}
        hosts = lambda: sorted({ln.split()[1] for ln in log.read_text().splitlines()})  # noqa: E731
        r["hosts_pack_install"] = hosts()
        step_py311(ctx, kind, env=env, key="py311_via_proxy")
        r["hosts_with_python_download"] = hosts()
    finally:
        proxy.kill()
    # Proxy unreachable: what does the user see, and how long does uv take to give up?
    env = dict(ctx.env, HTTPS_PROXY="http://127.0.0.1:9", UV_CACHE_DIR=str(ctx.work / "uv-cache-dead"))
    rm(pack)
    run([UV, "venv", "--python", PY, "--no-project", pack], env)
    secs, rc, out = run(
        [UV, "pip", "sync", "--python", pack_python(pack), "--require-hashes", "--no-build",
         "--torch-backend", PACKS[kind][2], lock_path(kind)],
        env, ok=False,
    )  # fmt: skip
    r["dead_proxy"] = {"s": secs, "rc": rc, "output": tail(out, 6)}
    for p in (pack, ctx.work / "uv-cache-proxy", ctx.work / "uv-cache-dead", ctx.work / "python-proxy"):
        rm(p)
    ctx.save("proxy", r)


def step_tls(ctx, kind):
    """Behind a TLS-intercepting proxy with its own CA (the cloud container): which trust settings work?"""
    bundle = os.environ.get("SSL_CERT_FILE")
    if not (os.environ.get("HTTPS_PROXY") and bundle):
        ctx.save("tls", {"skipped": "needs HTTPS_PROXY and SSL_CERT_FILE in the environment"})
        return
    clean = {k: v for k, v in ctx.env.items() if k not in ("SSL_CERT_FILE", "SSL_CERT_DIR", "UV_SYSTEM_CERTS")}
    no_proxy = {k: v for k, v in ctx.env.items() if k.upper() not in ("HTTPS_PROXY", "ALL_PROXY")}
    variants = {
        "default (bundled webpki roots)": ({}, []),
        "SSL_CERT_FILE=<proxy CA bundle>": ({"SSL_CERT_FILE": bundle}, []),
        "UV_SYSTEM_CERTS=1 (OS trust store)": ({"UV_SYSTEM_CERTS": "1"}, []),
        "--system-certs flag": ({}, ["--system-certs"]),
        "--native-tls flag (old name)": ({}, ["--native-tls"]),
    }
    r = {}
    for label, (extra, flags) in variants.items():
        cache = ctx.work / "uv-cache-tls"
        rm(cache)
        env = dict(clean, UV_CACHE_DIR=str(cache), **extra)
        secs, rc, out = run([*compile_cmd(kind, OS_NAME, ctx.work / "tls.txt"), *flags], env, ok=False)
        r[label] = {"rc": rc, "s": secs, "output": tail(out, 5) if rc else tail(out, 1)}
    rm(ctx.work / "uv-cache-tls")
    secs, rc, out = run(compile_cmd(kind, OS_NAME, ctx.work / "tls.txt"), dict(no_proxy, UV_CACHE_DIR=str(ctx.work / "uv-cache-tls")), ok=False)
    r["no proxy variable at all (direct connection is blocked here)"] = {"rc": rc, "s": secs, "output": tail(out, 5)}
    rm(ctx.work / "uv-cache-tls")
    ctx.save("tls", r)


def step_clean(ctx, kind):
    """`uv cache clean` while a pack still exists: hard-linked files stay alive in the pack."""
    pack = ctx.packs / ctx.name(kind)
    cache_only = usage(pack, ctx.work / "uv-cache")[0] - usage(pack)[0]
    free0 = free(ctx.work)
    secs, _, out = run([UV, "cache", "clean"], ctx.env)
    ctx.save("clean", {
        "clean_s": secs, "output": tail(out, 2), "free_space_gained_mb": mb(free(ctx.work) - free0),
        "cache_not_linked_from_a_pack_mb_before": mb(cache_only),
        "pack_still_works": "failed" not in ctx.check(pack, ok=False), "biggest_file": biggest_file(pack),
    })  # fmt: skip


def step_av(ctx, kind):
    """One warm install + first import, timed; the workflow runs it with Defender real-time scanning on and off."""
    pack = ctx.packs / ctx.name(kind, "-av")
    t_venv, t_sync, _ = ctx.install(kind, pack)
    check = ctx.check(pack)
    rm(pack)
    runs = ctx.results.get("av", [])
    row = {"label": os.environ.get("SPIKE_LABEL", ""), "warm_sync_s": t_sync, "first_import_s": check["import_s"]}
    ctx.save("av", [*runs, row])


CPU_STEPS = ["cold", "warm", "bytecode", "tamper", "move", "deep", "xvol", "relocate", "py311", "proxy", "tls", "av",
             "prune", "clean"]  # fmt: skip
CU12_STEPS = ["cold", "warm", "bytecode"]


def measure(args):
    work = Path(args.work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    ctx = Ctx(work, Path(args.other_volume).resolve() if args.other_volume else None)
    _, _, version = run([UV, "--version"], ctx.env)
    ctx.save("machine", {
        "os": OS_NAME, "platform": sys.platform, "uv": version.strip(), "cpus": os.cpu_count(),
        "vendored_python": tail(run([PY, "--version"], ctx.env)[2], 1)[0],
        "locks": {k: lock_hashes(lock_path(k)) for k in PACKS},
    })  # fmt: skip
    only = args.only.split(",") if args.only else None
    for kind in args.packs.split(","):
        for step in CPU_STEPS if kind == "cpu" else CU12_STEPS:
            if only and step not in only:
                continue
            print(f"\n===== {step} ({kind}) =====", flush=True)
            globals()[f"step_{step}"](ctx, kind)
        if kind == "cu12" and not only:  # free the disk: CUDA packs are several GB
            for p in (ctx.packs / ctx.name(kind), ctx.packs / ctx.name(kind, "-b")):
                rm(p)
    print("\n===== results.json =====")
    print(ctx.results_file.read_text())


def lock(args):
    """Generate all four locks on this machine (uv resolves for another OS with --python-platform)."""
    env, bad = base_env(), []
    for kind in PACKS:
        for os_name in UV_PLATFORMS:
            target = lock_path(kind, os_name)
            out = target.with_suffix(".check") if args.check else target
            target.parent.mkdir(exist_ok=True)
            run(compile_cmd(kind, os_name, out), env)
            if args.check:
                new, old = out.read_bytes(), target.read_bytes()
                out.unlink()
                same = new == old
                same_lf = new.replace(b"\r\n", b"\n") == old.replace(b"\r\n", b"\n")
                print(f"CHECK {target.relative_to(HERE)}: identical={same} identical_ignoring_crlf={same_lf} "
                      f"generated_has_crlf={b'\r\n' in new} committed_has_crlf={b'\r\n' in old}")  # fmt: skip
                if not same_lf:
                    bad.append(str(target))
    if bad:
        sys.exit(f"locks differ from the committed ones: {bad}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("lock")
    p.add_argument("--check", action="store_true")
    p = sub.add_parser("measure")
    p.add_argument("--work", required=True)
    p.add_argument("--packs", default="cpu")
    p.add_argument("--other-volume")
    p.add_argument("--only")
    args = parser.parse_args()
    {"lock": lock, "measure": measure}[args.cmd](args)
