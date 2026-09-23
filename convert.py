#!/usr/bin/env python3
"""
Wii Image Converter - RVZ <-> WBFS <-> ISO

Single file (drag & drop a .rvz, .wbfs or .iso onto convert.bat / the .exe):
    python convert.py "D:\\Wii\\ISO\\Game.iso" --to wbfs

Batch (every .iso in a folder -> .wbfs, what iso_to_wbfs.bat runs):
    python convert.py --batch "D:\\Wii\\ISO" --to wbfs --output "D:\\Wii\\wbfs"

Flows:
WBFS -> RVZ : WIT (WBFS->temporary ISO) + DolphinTool (ISO->RVZ) + temporary ISO cleanup
RVZ -> WBFS : DolphinTool (RVZ->temporary ISO) + WIT (ISO->WBFS) + temporary ISO cleanup
ISO -> RVZ : direct DolphinTool conversion (original ISO is NOT deleted)
ISO -> WBFS : direct WIT conversion (original ISO is NOT deleted)

Only the tool a flow needs is required. wit.exe is downloaded automatically
(into .\\tools\\wit\\) when it cannot be found, so ISO -> WBFS needs nothing
but Python.
"""

import sys
import os
import subprocess
import configparser
import time
import tempfile
import shutil
import ctypes
import argparse
import hashlib
import platform
import struct
import zipfile
import urllib.request
import urllib.error
from pathlib import Path

IS_WINDOWS = os.name == "nt"

# ── ANSI colors ──────────────────────────────────────────────────────────────
def _enable_ansi() -> bool:
    """Turn on VT escape processing in the classic Windows console."""
    if not IS_WINDOWS:
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False  # not a console (redirected) - colors are harmless there
        if mode.value & 0x0004:
            return True
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False

if _enable_ansi():
    GREEN, YELLOW, RED, CYAN, RESET, BOLD = (
        "\033[92m", "\033[93m", "\033[91m", "\033[96m", "\033[0m", "\033[1m")
else:
    GREEN = YELLOW = RED = CYAN = RESET = BOLD = ""

def info(msg): print(f"{CYAN}[INFO]{RESET} {msg}")
def ok(msg): print(f"{GREEN}[OK]{RESET} {msg}")
def warn(msg): print(f"{YELLOW}[WARN]{RESET} {msg}")
def error(msg): print(f"{RED}[ERR]{RESET} {msg}")
def step(n, msg): print(f"\n{BOLD}-- Step {n}: {msg}{RESET}")

# ── Base path ────────────────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent.resolve()
else:
    BASE_DIR = Path(__file__).parent.resolve()

CONFIG_FILE = BASE_DIR / "config.ini"
NO_PAUSE = "--no-pause" in sys.argv

DEFAULT_CONFIG = """\
[paths]
# Leave empty to auto-detect (next to the script, .\\tools\\, PATH, common install folders).
# wit.exe is downloaded automatically into .\\tools\\wit\\ if it cannot be found.
dolphin_tool =
wit_tool =

[output]
output_rvz = .\\RVZ
output_wbfs = D:\\Wii\\wbfs

[conversion]
rvz_compression = zstd
rvz_compression_level = 5

[batch]
input_iso = D:\\Wii\\ISO
output_wbfs = D:\\Wii\\wbfs
# Output file name. Placeholders: {name} = ISO file name, {id} = 6-char game ID, {title} = disc title
name_format = {name} [{id}]
"""

# ── WIT auto-download ────────────────────────────────────────────────────────
# Official builds from https://wit.wiimm.de/download.html (Wiimms ISO Tools, GPL-2.0).
WIT_VERSION = "v3.05a-r8638"
WIT_DOWNLOADS = {
    # key: (url, sha256, folder inside the zip that holds wit.exe + its DLLs)
    "win64": (f"https://wit.wiimm.de/download/wit-{WIT_VERSION}-cygwin64.zip",
              "049670558970f0cea2796d68e0ba1e48491474b5708bf12a95ab8a185f4e59c1",
              f"wit-{WIT_VERSION}-cygwin64/bin"),
    "win32": (f"https://wit.wiimm.de/download/wit-{WIT_VERSION}-cygwin32.zip",
              "c939189f19454fce0c50a92e368d5ec5430e690002d5095de48a6fcc8e4ecd33",
              f"wit-{WIT_VERSION}-cygwin32/bin"),
}
WIT_EXE_NAME = "wit.exe" if IS_WINDOWS else "wit"
DOLPHIN_EXE_NAME = "DolphinTool.exe" if IS_WINDOWS else "dolphin-tool"

def _user_tools_dir() -> Path:
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "WiiFormatConverter" / "tools"
    return Path.home() / ".local" / "share" / "WiiFormatConverter" / "tools"

TOOLS_DIRS = [BASE_DIR / "tools", _user_tools_dir()]

TOOL_CANDIDATES = {
    "dolphin_tool": [
        DOLPHIN_EXE_NAME,
        r"C:\Dolphin\DolphinTool.exe",
        r"C:\Program Files\Dolphin\DolphinTool.exe",
        r"C:\Program Files (x86)\Dolphin\DolphinTool.exe",
    ],
    "wit_tool": [
        WIT_EXE_NAME,
        r"C:\WiimmsISOTools\wit.exe",
        r"C:\WiimmsISOTools\bin\wit.exe",
        r"C:\Program Files\Wiimm\WIT\wit.exe",
        r"C:\Program Files (x86)\Wiimm\WIT\wit.exe",
        r"C:\Program Files\wit\bin\wit.exe",
        r"C:\wit\wit.exe",
        r"C:\wit\bin\wit.exe",
    ],
}

def _tool_runs(exe: Path, args=("--version",)) -> bool:
    """Smoke test: the binary starts and exits cleanly (catches missing DLLs)."""
    try:
        r = subprocess.run([str(exe), *args], capture_output=True, timeout=60)
        return r.returncode == 0
    except Exception:
        return False

def _download(url: str, dest: Path, expected_sha256: str = ""):
    """Download url to dest with a progress line; verify sha256 when given."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "WiiFormatConverter/1.1"})
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        t_last = 0.0
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
            h.update(chunk)
            done += len(chunk)
            now = time.time()
            if now - t_last > 0.25 or done == total:
                t_last = now
                if total:
                    pct = done * 100 // total
                    print(f"\r    {done / 1_048_576:6.1f} / {total / 1_048_576:.1f} MB  ({pct:3d}%)",
                          end="", flush=True)
                else:
                    print(f"\r    {done / 1_048_576:6.1f} MB", end="", flush=True)
    print()
    digest = h.hexdigest()
    if expected_sha256 and digest.lower() != expected_sha256.lower():
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"SHA-256 mismatch for {url}\n"
                           f"      expected {expected_sha256}\n"
                           f"      got      {digest}")
    tmp.replace(dest)

def _extract_subdir(zip_path: Path, subdir: str, target: Path):
    """Extract everything under <subdir>/ in the zip into target (flattened to target/)."""
    prefix = subdir.strip("/").replace("\\", "/") + "/"
    target.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            name = member.filename.replace("\\", "/")
            if member.is_dir() or not name.startswith(prefix):
                continue
            rel = Path(name[len(prefix):])
            if not rel.parts or ".." in rel.parts or rel.is_absolute():
                continue  # zip-slip guard
            out = target / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
            if not IS_WINDOWS:
                out.chmod(0o755)
            count += 1
    return count

def _writable_dir(candidates):
    for d in candidates:
        try:
            d.mkdir(parents=True, exist_ok=True)
            probe = d / ".write_test"
            probe.write_text("ok")
            probe.unlink()
            return d
        except OSError:
            continue
    return None

def install_wit() -> Path:
    """Download the official WIT build and unpack wit.exe (+DLLs) into tools/wit/."""
    if os.environ.get("WII_CONV_WIT_URL"):  # test / advanced override
        url = os.environ["WII_CONV_WIT_URL"]
        sha = os.environ.get("WII_CONV_WIT_SHA256", "")
        subdir = os.environ.get("WII_CONV_WIT_SUBDIR", "bin")
    else:
        if not IS_WINDOWS:
            raise RuntimeError("Automatic WIT download is only available on Windows. "
                               "Install wit from https://wit.wiimm.de/ and set wit_tool in config.ini.")
        is64 = platform.machine().upper() not in ("X86", "I386", "I686", "")
        url, sha, subdir = WIT_DOWNLOADS["win64" if is64 else "win32"]

    tools_dir = _writable_dir(TOOLS_DIRS)
    if tools_dir is None:
        raise RuntimeError("No writable folder for tools (tried: "
                           + ", ".join(str(d) for d in TOOLS_DIRS) + ")")
    wit_dir = tools_dir / "wit"
    zip_path = tools_dir / Path(url.split("?")[0]).name

    info(f"Downloading Wiimms ISO Tools {WIT_VERSION}")
    info(f"From : {url}")
    info(f"To   : {wit_dir}")
    _download(url, zip_path, sha)
    if sha:
        ok("Checksum verified (SHA-256)")
    n = _extract_subdir(zip_path, subdir, wit_dir)
    zip_path.unlink(missing_ok=True)
    exe = wit_dir / WIT_EXE_NAME
    if n == 0 or not exe.exists():
        raise RuntimeError(f"{WIT_EXE_NAME} not found inside the downloaded archive ({subdir}/)")
    ok(f"Unpacked {n} file(s)")
    if not _tool_runs(exe):
        raise RuntimeError(f"{exe} was unpacked but does not start. "
                           "Try installing WIT manually from https://wit.wiimm.de/")
    ok(f"WIT ready: {exe}")
    return exe

# ── Config ───────────────────────────────────────────────────────────────────
def load_config():
    cfg = configparser.ConfigParser()
    if not CONFIG_FILE.exists():
        info(f"config.ini not found - creating it with default settings: {CONFIG_FILE}")
        try:
            CONFIG_FILE.write_text(DEFAULT_CONFIG, encoding="utf-8")
        except OSError as exc:
            warn(f"Could not write config.ini ({exc}); continuing with built-in defaults.")
            cfg.read_string(DEFAULT_CONFIG)
            return cfg
    try:
        cfg.read(CONFIG_FILE, encoding="utf-8")
    except configparser.Error as exc:
        warn(f"config.ini could not be parsed ({exc}); continuing with built-in defaults.")
        cfg = configparser.ConfigParser()
        cfg.read_string(DEFAULT_CONFIG)
    return cfg

def resolve_tool(cfg, key, allow_download=True):
    """
    Locate a tool. Order: config.ini path -> next to the script/.exe ->
    .\\tools\\<name>\\ -> system PATH -> well-known install folders ->
    (wit only) automatic download.
    Returns (path, found).
    """
    exe_name = TOOL_CANDIDATES[key][0]
    raw = cfg.get("paths", key, fallback="").strip()
    configured = None
    if raw:
        configured = Path(raw)
        if not configured.is_absolute():
            configured = BASE_DIR / configured
        configured = configured.resolve()
        if configured.is_file():
            return configured, True
        if configured.is_dir() and (configured / exe_name).is_file():
            return (configured / exe_name).resolve(), True
        warn(f"Configured {key} does not exist: {configured} - trying auto-detection")

    sub = "wit" if key == "wit_tool" else "dolphin"
    for d in [BASE_DIR] + [t / sub for t in TOOLS_DIRS] + list(TOOLS_DIRS):
        c = d / exe_name
        if c.is_file():
            return c.resolve(), True

    on_path = shutil.which(exe_name) or shutil.which(Path(exe_name).stem)
    if on_path:
        return Path(on_path).resolve(), True

    for cand in TOOL_CANDIDATES[key][1:]:
        c = Path(cand)
        if c.is_file():
            return c.resolve(), True

    if key == "wit_tool" and allow_download:
        warn(f"{exe_name} not found anywhere - downloading it now")
        try:
            return install_wit(), True
        except (RuntimeError, OSError, urllib.error.URLError, zipfile.BadZipFile) as exc:
            error(f"Automatic WIT download failed: {exc}")
            error("Manual fix: download the cygwin64 zip from https://wit.wiimm.de/download.html,")
            error(f"unzip it, and copy the whole 'bin' folder contents to: {BASE_DIR / 'tools' / 'wit'}")
            error("(or set wit_tool in config.ini to your wit.exe)")

    return (configured or Path(exe_name)), False

def get_output_dir(cfg, fmt: str, override: str = None) -> Path:
    key = "output_rvz" if fmt == "rvz" else "output_wbfs"
    default = f".\\{fmt.upper()}"
    raw = (override or cfg.get("output", key, fallback=default)).strip()
    p = Path(raw)
    if not p.is_absolute():
        p = BASE_DIR / p
    p = p.resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p

# ── Disc headers ─────────────────────────────────────────────────────────────
WII_MAGIC = 0x5D1C9EA3   # big-endian at disc offset 0x18
GC_MAGIC = 0xC2339F3D    # big-endian at disc offset 0x1C

def read_disc_header(path: Path):
    """
    Return {'id': 'RMGE01', 'title': '...', 'wii': bool, 'gc': bool} for a plain
    .iso or a .wbfs file, or None if the header cannot be read / is not a disc.
    """
    try:
        with open(path, "rb") as f:
            if path.suffix.lower() == ".wbfs":
                head = f.read(16)
                if len(head) < 16 or head[:4] != b"WBFS":
                    return None
                f.seek(1 << head[8])   # first disc header copy = second HD sector
            hdr = f.read(0x60)
    except OSError:
        return None
    if len(hdr) < 0x60:
        return None
    id6 = hdr[:6]
    if not all(0x30 <= b <= 0x5A or 0x61 <= b <= 0x7A for b in id6):
        return None
    wii = struct.unpack(">I", hdr[0x18:0x1C])[0] == WII_MAGIC
    gc = struct.unpack(">I", hdr[0x1C:0x20])[0] == GC_MAGIC
    title = hdr[0x20:0x60].split(b"\0", 1)[0].decode("ascii", "replace").strip()
    return {"id": id6.decode("ascii"), "title": title, "wii": wii, "gc": gc}

def index_existing_wbfs(out_dir: Path) -> dict:
    """Map game ID -> path for every .wbfs already under out_dir (any naming scheme)."""
    index = {}
    try:
        for p in out_dir.rglob("*"):
            if not p.is_file() or p.suffix.lower() != ".wbfs":
                continue
            if STAGING_NAME in p.parts:
                continue
            if p.stat().st_size == 0:
                continue
            hdr = read_disc_header(p)
            if hdr:
                index.setdefault(hdr["id"], p)
    except OSError as exc:
        warn(f"Could not fully scan {out_dir}: {exc}")
    return index

_BAD_FS_CHARS = '<>:"/\\|?*'

def safe_filename(name: str) -> str:
    cleaned = "".join("_" if (c in _BAD_FS_CHARS or ord(c) < 32) else c for c in name)
    return cleaned.strip(" .") or "game"

def wbfs_name_for(source: Path, hdr, name_format: str) -> str:
    """Build the .wbfs file name (without extension) from the configured format."""
    stem = source.stem
    if not hdr:
        return stem
    if hdr["id"] in stem.upper():          # already named like "Title [RMGE01]" or "RMGE01"
        return stem
    try:
        name = name_format.format(name=stem, id=hdr["id"], title=hdr["title"] or stem)
    except (KeyError, IndexError, ValueError):
        warn(f"Invalid name_format '{name_format}', using '{{name}} [{{id}}]'")
        name = f"{stem} [{hdr['id']}]"
    return safe_filename(name)

# ── Filesystem helpers ───────────────────────────────────────────────────────
STAGING_NAME = ".incomplete"

def filesystem_name(path: Path):
    """'NTFS', 'FAT32', 'exFAT', ... on Windows; None elsewhere or on failure."""
    if not IS_WINDOWS:
        return None
    try:
        root = Path(path).resolve().anchor
        if not root:
            return None
        buf = ctypes.create_unicode_buffer(64)
        res = ctypes.windll.kernel32.GetVolumeInformationW(
            root, None, 0, None, None, None, buf, 64)
        return buf.value if res else None
    except Exception:
        return None

def enough_space(target_dir: Path, needed_bytes: int) -> bool:
    try:
        return shutil.disk_usage(target_dir).free >= needed_bytes
    except OSError:
        return True  # cannot tell - let the tool try

def clean_staging(out_dir: Path):
    stage = out_dir / STAGING_NAME
    if not stage.exists():
        return
    leftovers = [p for p in stage.iterdir() if p.is_file()]
    for p in leftovers:
        warn(f"Removing unfinished file from an earlier run: {p.name}")
        try:
            p.unlink()
        except OSError as exc:
            warn(f"  could not delete {p}: {exc}")

# ── Utilities ────────────────────────────────────────────────────────────────
def run_cmd(cmd: list, desc: str) -> bool:
    info(f"Command: {' '.join(str(c) for c in cmd)}")
    print()
    t0 = time.time()
    try:
        result = subprocess.run(cmd)
    except OSError as exc:
        error(f"{desc} could not start: {exc}")
        return False
    elapsed = time.time() - t0
    if result.returncode != 0:
        error(f"{desc} failed (exit code {result.returncode})")
        return False
    ok(f"{desc} completed in {elapsed:.1f}s")
    return True

def print_sizes(src: Path, dst: Path, show_ratio=False):
    mb_src = src.stat().st_size / 1_048_576
    mb_dst = dst.stat().st_size / 1_048_576
    info(f"Source : {mb_src:,.1f} MB")
    info(f"Output : {mb_dst:,.1f} MB")
    if show_ratio and mb_src > 0:
        info(f"Saved  : {(1 - mb_dst / mb_src) * 100:.1f}%")

def pause(msg="\nPress ENTER to exit..."):
    if NO_PAUSE:
        return
    try:
        input(msg)
    except (EOFError, KeyboardInterrupt):
        print()

# ── Conversions ──────────────────────────────────────────────────────────────
def convert_wbfs_to_rvz(source: Path, cfg, dolphin: Path, wit: Path, out_dir: Path = None):
    if out_dir is None:
        out_dir = get_output_dir(cfg, "rvz")
    dest = out_dir / (source.stem + ".rvz")
    comp = cfg.get("conversion", "rvz_compression", fallback="zstd")
    level = cfg.get("conversion", "rvz_compression_level", fallback="5")

    tmp_dir = Path(tempfile.mkdtemp(prefix="wii_conv_"))
    iso_tmp = tmp_dir / (source.stem + ".iso")

    try:
        step(1, "WBFS -> ISO (wit, temporary file)")
        info(f"Source   : {source}")
        info(f"Temp ISO : {iso_tmp}")
        if not run_cmd([
            str(wit), "copy", str(source), str(iso_tmp),
            "--iso", "--overwrite",
        ], "WBFS -> ISO"):
            return False

        step(2, "ISO -> RVZ (DolphinTool)")
        info(f"Temp ISO : {iso_tmp}")
        info(f"Dest     : {dest}")
        if not run_cmd([
            str(dolphin), "convert",
            "--input", str(iso_tmp),
            "--output", str(dest),
            "--format", "rvz",
            "--compression", comp,
            "--compression_level", level,
            "--block_size", "131072",
        ], "ISO -> RVZ"):
            return False

        step(3, "Result")
        ok(f"Created file: {dest}")
        if dest.exists():
            print_sizes(source, dest, show_ratio=True)
        return True

    finally:
        step("*", "Temporary ISO cleanup")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        ok(f"Removed temp folder: {tmp_dir}")

def convert_rvz_to_wbfs(source: Path, cfg, dolphin: Path, wit: Path, out_dir: Path = None):
    if out_dir is None:
        out_dir = get_output_dir(cfg, "wbfs")
    dest = out_dir / (source.stem + ".wbfs")

    tmp_dir = Path(tempfile.mkdtemp(prefix="wii_conv_"))
    iso_tmp = tmp_dir / (source.stem + ".iso")

    try:
        step(1, "RVZ -> ISO (DolphinTool, temporary file)")
        info(f"Source   : {source}")
        info(f"Temp ISO : {iso_tmp}")
        if not run_cmd([
            str(dolphin), "convert",
            "--input", str(source),
            "--output", str(iso_tmp),
            "--format", "iso",
        ], "RVZ -> ISO"):
            return False

        step(2, "ISO -> WBFS (wit)")
        info(f"Temp ISO : {iso_tmp}")
        info(f"Dest     : {dest}")
        if not run_cmd([
            str(wit), "copy", str(iso_tmp), str(dest),
            "--wbfs", "--overwrite",
        ], "ISO -> WBFS"):
            return False

        step(3, "Result")
        ok(f"Created file: {dest}")
        if dest.exists():
            print_sizes(source, dest)
        return True

    finally:
        step("*", "Temporary ISO cleanup")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        ok(f"Removed temp folder: {tmp_dir}")

def convert_iso_to_rvz(source: Path, cfg, dolphin: Path, out_dir: Path = None):
    """The original ISO is NOT deleted."""
    if out_dir is None:
        out_dir = get_output_dir(cfg, "rvz")
    dest = out_dir / (source.stem + ".rvz")
    comp = cfg.get("conversion", "rvz_compression", fallback="zstd")
    level = cfg.get("conversion", "rvz_compression_level", fallback="5")

    step(1, "ISO -> RVZ (DolphinTool)")
    info(f"Source : {source}")
    info(f"Dest   : {dest}")
    if not run_cmd([
        str(dolphin), "convert",
        "--input", str(source),
        "--output", str(dest),
        "--format", "rvz",
        "--compression", comp,
        "--compression_level", level,
        "--block_size", "131072",
    ], "ISO -> RVZ"):
        return False

    step(2, "Result")
    ok(f"Created file: {dest}")
    ok(f"Original ISO preserved: {source}")
    if dest.exists():
        print_sizes(source, dest, show_ratio=True)
    return True

def convert_iso_to_wbfs(source: Path, cfg, wit: Path, out_dir: Path = None,
                        skip_existing: bool = False, existing_index: dict = None,
                        name_format: str = "{name}", split: bool = False):
    """
    ISO -> WBFS. The original ISO is NOT deleted.
    Writes into <out_dir>/.incomplete/ first and moves the result into place
    only when wit succeeds, so an interrupted run never leaves a file that
    looks finished.
    Returns True (converted), False (failed) or None (skipped).
    """
    if out_dir is None:
        out_dir = get_output_dir(cfg, "wbfs")
    hdr = read_disc_header(source)
    base = wbfs_name_for(source, hdr, name_format)
    dest = out_dir / (base + ".wbfs")

    if hdr:
        kind = "Wii" if hdr["wii"] else ("GameCube" if hdr["gc"] else "unknown type")
        info(f"Disc   : {hdr['id']}  {hdr['title']}  ({kind})")
        if not hdr["wii"] and not hdr["gc"]:
            warn("Header has no Wii/GameCube magic - this may not be a disc image")
    else:
        warn("Could not read a disc header - is this really a Wii ISO?")

    if skip_existing:
        if dest.exists() and dest.stat().st_size > 0:
            warn(f"Already exists, skipping: {dest.name}")
            return None
        if hdr and existing_index and hdr["id"] in existing_index:
            warn(f"Already converted as {existing_index[hdr['id']].name} "
                 f"(same game ID {hdr['id']}), skipping")
            return None

    needed = source.stat().st_size + 64 * 1_048_576
    if not enough_space(out_dir, needed):
        free = shutil.disk_usage(out_dir).free / 1_073_741_824
        error(f"Not enough free space on {out_dir.anchor or out_dir} "
              f"({free:.1f} GB free, {needed / 1_073_741_824:.1f} GB needed)")
        return False

    stage_dir = out_dir / STAGING_NAME
    stage_dir.mkdir(parents=True, exist_ok=True)
    staged = stage_dir / dest.name

    step(1, "ISO -> WBFS (wit)")
    info(f"Source : {source}")
    info(f"Dest   : {dest}")
    cmd = [str(wit), "copy", str(source), str(staged), "--wbfs", "--overwrite"]
    if split:
        cmd += ["--split", "--split-size", "4G-32K"]
    success = run_cmd(cmd, "ISO -> WBFS")

    # Everything wit produced for this game (name.wbfs, and name.wbf1... when split)
    parts = sorted(p for p in stage_dir.iterdir()
                   if p.is_file() and p.stem == staged.stem)
    if not success:
        for p in parts:
            p.unlink(missing_ok=True)
        if parts:
            warn("Removed partial output")
        return False
    if not parts or not staged.exists() or staged.stat().st_size == 0:
        error("wit reported success but produced no output file")
        for p in parts:
            p.unlink(missing_ok=True)
        return False

    for p in parts:
        final = out_dir / p.name
        if final.exists():
            final.unlink()
        shutil.move(str(p), str(final))

    step(2, "Result")
    ok(f"Created file: {dest}")
    if len(parts) > 1:
        ok(f"Split into {len(parts)} parts (FAT32 4 GB limit)")
    ok(f"Original ISO preserved: {source}")
    if dest.exists():
        print_sizes(source, dest)
    if existing_index is not None and hdr:
        existing_index.setdefault(hdr["id"], dest)
    return True

def batch_iso_to_wbfs(in_dir: Path, out_dir: Path, cfg, wit: Path,
                      overwrite: bool = False) -> bool:
    """Convert every .iso under in_dir to .wbfs in out_dir. Returns True if nothing failed."""
    name_format = cfg.get("batch", "name_format", fallback="{name} [{id}]").strip() or "{name}"
    out_res = out_dir.resolve()

    isos = []
    for p in sorted(in_dir.rglob("*")):
        if not p.is_file() or p.suffix.lower() != ".iso":
            continue
        try:
            if out_res == p.parent.resolve() or out_res in p.parent.resolve().parents:
                continue  # never treat the output folder as input
        except OSError:
            pass
        isos.append(p)

    if not isos:
        warn(f"No .iso files found in: {in_dir}")
        warn("Put your Wii ISO files in that folder and run this again.")
        return True

    clean_staging(out_dir)
    fs = filesystem_name(out_dir)
    split = fs is not None and fs.upper().startswith("FAT")   # FAT / FAT32: 4 GB file limit
    if fs:
        info(f"Output filesystem: {fs}" + ("  -> large games will be split at 4 GB" if split else ""))

    existing = {} if overwrite else index_existing_wbfs(out_dir)
    if existing:
        info(f"{len(existing)} game(s) already present in {out_dir}")

    info(f"Found {len(isos)} ISO file(s) in {in_dir}")
    print()
    converted, skipped, failed = [], [], []
    t0 = time.time()

    for i, iso in enumerate(isos, 1):
        print(f"\n{BOLD}{CYAN}=== [{i}/{len(isos)}] {iso.name} "
              f"({iso.stat().st_size / 1_048_576:,.1f} MB) ==={RESET}")
        try:
            res = convert_iso_to_wbfs(iso, cfg, wit, out_dir=out_dir,
                                      skip_existing=not overwrite,
                                      existing_index=existing,
                                      name_format=name_format, split=split)
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # keep going with the rest of the folder
            error(f"Unexpected error: {exc}")
            res = False
        if res is None:
            skipped.append(iso.name)
        elif res:
            converted.append(iso.name)
        else:
            failed.append(iso.name)

    try:
        (out_dir / STAGING_NAME).rmdir()   # only succeeds when empty
    except OSError:
        pass

    elapsed = time.time() - t0
    print(f"\n{BOLD}{CYAN}=========== Batch summary ==========={RESET}")
    ok(f"Converted : {len(converted)}")
    warn(f"Skipped   : {len(skipped)} (already in {out_dir})")
    if failed:
        error(f"Failed    : {len(failed)}")
        for name in failed:
            error(f"   - {name}")
    else:
        ok("Failed    : 0")
    info(f"Total time: {elapsed / 60:.1f} min")
    return not failed

# ── Main ─────────────────────────────────────────────────────────────────────
def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="convert.py",
        description="Wii image converter: RVZ <-> WBFS <-> ISO (single file or batch).",
    )
    parser.add_argument("source", nargs="?",
                        help="A .rvz, .wbfs or .iso file (drag & drop target).")
    parser.add_argument("--batch", metavar="FOLDER", nargs="?", const="",
                        help="Convert every .iso in FOLDER (batch mode). Without a value, "
                             "uses [batch] input_iso from config.ini.")
    parser.add_argument("--to", choices=["rvz", "wbfs"],
                        help="Target format for ISO input. Skips the Yes/No dialog.")
    parser.add_argument("--output", metavar="FOLDER",
                        help="Output folder. Overrides config.ini.")
    parser.add_argument("--overwrite", action="store_true",
                        help="Batch mode: re-convert games that already exist in the output folder.")
    parser.add_argument("--no-download", action="store_true",
                        help="Never download wit.exe automatically.")
    parser.add_argument("--no-pause", action="store_true",
                        help="Do not wait for ENTER before exiting.")
    return parser.parse_args(argv)

def fail(msg: str, code: int = 1):
    error(msg)
    pause()
    sys.exit(code)

def require_tool(cfg, key, label, allow_download):
    tool, found = resolve_tool(cfg, key, allow_download=allow_download)
    if not found:
        error(f"{label} not found: {tool}")
        if key == "dolphin_tool":
            error("Install Dolphin (https://dolphin-emu.org/download/) or set dolphin_tool in config.ini.")
        else:
            error("Install Wiimms ISO Tools (https://wit.wiimm.de/) or set wit_tool in config.ini.")
        pause()
        sys.exit(1)
    ok(f"{label:<11} : {tool}")
    return tool

def ask_format_dialog(filename: str) -> str:
    """
    Native Windows Yes/No dialog: Yes -> RVZ, No -> WBFS.
    Falls back to a console prompt when no GUI is available.
    """
    if IS_WINDOWS:
        MB_YESNO, MB_ICONQUESTION, IDYES, IDNO = 0x4, 0x20, 6, 7
        msg = (f"ISO file detected:\n{filename}\n\n"
               f"Which format do you want to convert it to?\n\n"
               f" [Yes] -> RVZ\n"
               f" [No] -> WBFS")
        result = ctypes.windll.user32.MessageBoxW(
            0, msg, "Wii Converter - Choose output format", MB_YESNO | MB_ICONQUESTION)
        if result == IDYES:
            return "rvz"
        if result == IDNO:
            return "wbfs"
        warn("Dialog closed without a selection. Exiting.")
        sys.exit(0)
    while True:
        ans = input(f"Convert {filename} to [r]vz or [w]bfs? ").strip().lower()
        if ans in ("r", "rvz"):
            return "rvz"
        if ans in ("w", "wbfs"):
            return "wbfs"

def main():
    print(f"\n{BOLD}{CYAN}=========================================={RESET}")
    print(f"{BOLD}{CYAN} Wii Converter | RVZ <-> WBFS <-> ISO{RESET}")
    print(f"{BOLD}{CYAN}=========================================={RESET}\n")

    args = parse_args(sys.argv[1:])
    allow_download = not args.no_download

    # ── Batch mode: folder of ISOs -> WBFS ─────────────────────────────────
    if args.batch is not None:
        if args.to and args.to != "wbfs":
            fail("Batch mode currently supports ISO -> WBFS only (--to wbfs).")

        cfg = load_config()
        in_raw = args.batch or cfg.get("batch", "input_iso", fallback="").strip()
        if not in_raw:
            fail("No input folder. Use --batch <folder> or set [batch] input_iso in config.ini.")
        in_dir = Path(in_raw).resolve()

        step(0, "Checking folders")
        if not in_dir.is_dir():
            try:
                in_dir.mkdir(parents=True)
            except OSError as exc:
                fail(f"Input folder does not exist and could not be created: {in_dir} ({exc})")
            warn(f"Input folder did not exist, created it: {in_dir}")
            warn("Put your Wii ISO files in that folder and run this again.")
            pause("\nPress ENTER to close...")
            sys.exit(0)
        ok(f"Input dir  : {in_dir}")
        ok(f"Base       : {BASE_DIR}")

        out_override = args.output or cfg.get("batch", "output_wbfs", fallback="").strip() or None
        try:
            out_dir = get_output_dir(cfg, "wbfs", override=out_override)
        except OSError as exc:
            fail(f"Output folder could not be created: {out_override} ({exc})")
        ok(f"Output dir : {out_dir}")
        if out_dir == in_dir:
            fail("Input and output folder are the same - choose a different output folder.")

        step(1, "Checking tools")
        wit = require_tool(cfg, "wit_tool", "WIT", allow_download)

        success = batch_iso_to_wbfs(in_dir, out_dir, cfg, wit, overwrite=args.overwrite)
        print()
        if success:
            print(f"{BOLD}{GREEN}OK Batch conversion completed successfully!{RESET}")
        else:
            print(f"{BOLD}{RED}XX Some conversions failed. Check the messages above.{RESET}")
        pause("\nPress ENTER to close...")
        sys.exit(0 if success else 1)

    # ── Single-file mode ───────────────────────────────────────────────────
    if not args.source:
        warn("No file specified.")
        warn("Drag and drop a .rvz, .wbfs, or .iso file onto convert.bat or the .exe,")
        warn('or run in batch mode:  convert.py --batch "D:\\Wii\\ISO" --to wbfs --output "D:\\Wii\\wbfs"')
        pause()
        sys.exit(1)

    source = Path(args.source).resolve()

    step(0, "Checking source file")
    if not source.is_file():
        fail(f"File not found: {source}")

    ext = source.suffix.lower()
    if ext not in (".rvz", ".wbfs", ".iso"):
        error(f"Unsupported format: '{ext}'")
        fail("Supported formats: .rvz .wbfs .iso")

    ok(f"File : {source.name} ({source.stat().st_size / 1_048_576:,.1f} MB)")
    ok(f"Base : {BASE_DIR}")

    cfg = load_config()

    # ── Output format selection for ISO ────────────────────────────────────
    iso_target_fmt = None
    if ext == ".iso":
        iso_target_fmt = args.to or ask_format_dialog(source.name)
        info(f"Selected format: {iso_target_fmt.upper()}")

    fmt_dest = {
        ".wbfs": "rvz",
        ".rvz": "wbfs",
        ".iso": iso_target_fmt,
    }[ext]

    # Only require the tools the chosen flow actually uses.
    needs_dolphin = fmt_dest == "rvz" or ext == ".rvz"
    needs_wit = fmt_dest == "wbfs" or ext == ".wbfs"
    dolphin = require_tool(cfg, "dolphin_tool", "DolphinTool", False) if needs_dolphin else None
    wit = require_tool(cfg, "wit_tool", "WIT", allow_download) if needs_wit else None

    out_dir = get_output_dir(cfg, fmt_dest, override=args.output)
    ok(f"Output dir : {out_dir}")

    # ── Conversion ──────────────────────────────────────────────────────────
    if ext == ".wbfs":
        success = convert_wbfs_to_rvz(source, cfg, dolphin, wit, out_dir=out_dir)
    elif ext == ".rvz":
        success = convert_rvz_to_wbfs(source, cfg, dolphin, wit, out_dir=out_dir)
    elif ext == ".iso" and iso_target_fmt == "rvz":
        success = convert_iso_to_rvz(source, cfg, dolphin, out_dir=out_dir)
    else:
        name_format = cfg.get("batch", "name_format", fallback="{name} [{id}]").strip() or "{name}"
        fs = filesystem_name(out_dir)
        split = fs is not None and fs.upper().startswith("FAT")
        success = convert_iso_to_wbfs(source, cfg, wit, out_dir=out_dir,
                                      name_format=name_format, split=split)

    print()
    if success:
        print(f"{BOLD}{GREEN}OK Conversion completed successfully!{RESET}")
    else:
        print(f"{BOLD}{RED}XX Conversion failed. Check the messages above.{RESET}")

    pause("\nPress ENTER to close...")
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        warn("Interrupted by user.")
        sys.exit(130)
    except SystemExit:
        raise
    except Exception:
        import traceback
        print()
        traceback.print_exc()
        error("Unexpected error - see the message above.")
        pause("\nPress ENTER to close...")
        sys.exit(1)
