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

NKit images (*.nkit.iso, "NKIT" magic at 0x200) are not real ISOs and wit
cannot read them. They are handled with NKit 2 (downloaded automatically into
.\\tools\\nkit\\): either converted straight to WBFS, or expanded to a full
ISO first and then passed to wit.
"""

import sys
import os
import re
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
# NKit 2 command line tool (nkit.exe), only needed for *.nkit.iso images.
# Downloaded automatically into .\\tools\\nkit\\ if it cannot be found.
nkit_tool =

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
# How *.nkit.iso images are handled: wbfs = NKit writes the WBFS directly (fast, no temp file)
#                                     iso  = NKit restores a full ISO first, then wit makes the WBFS
# If "wbfs" fails for a game, "iso" is tried automatically.
nkit_mode = wbfs
"""

# ── Tool auto-download ───────────────────────────────────────────────────────
# WIT : official builds from https://wit.wiimm.de/download.html (Wiimms ISO Tools, GPL-2.0)
# NKit: official builds from https://github.com/Nanook/NKit/releases (self-contained, no .NET needed)
WIT_VERSION = "v3.05a-r8638"
NKIT_VERSION = "2.1.0"
TOOL_DOWNLOADS = {
    # key -> arch -> (url, sha256, folder inside the zip that holds the exe; "" = whole zip)
    "wit_tool": {
        "win64": (f"https://wit.wiimm.de/download/wit-{WIT_VERSION}-cygwin64.zip",
                  "049670558970f0cea2796d68e0ba1e48491474b5708bf12a95ab8a185f4e59c1",
                  f"wit-{WIT_VERSION}-cygwin64/bin"),
        "win32": (f"https://wit.wiimm.de/download/wit-{WIT_VERSION}-cygwin32.zip",
                  "c939189f19454fce0c50a92e368d5ec5430e690002d5095de48a6fcc8e4ecd33",
                  f"wit-{WIT_VERSION}-cygwin32/bin"),
    },
    "nkit_tool": {
        "win64": (f"https://github.com/Nanook/NKit/releases/download/v{NKIT_VERSION}/NKit_CLI_win-x64_{NKIT_VERSION}.zip",
                  "e2a66cc9b6c3e22aa5fa3d7a4c245a5d35efe0c757e5db2ffcb8690f33537e97",
                  ""),
        "winarm64": (f"https://github.com/Nanook/NKit/releases/download/v{NKIT_VERSION}/NKit_CLI_win-arm64_{NKIT_VERSION}.zip",
                     "6e152e37b949330ee40cda1b8b241a98c7329851f87f86b3a8f61b7046b334de",
                     ""),
    },
}
TOOL_LABELS = {"wit_tool": "Wiimms ISO Tools " + WIT_VERSION, "nkit_tool": "NKit " + NKIT_VERSION}
TOOL_SUBDIRS = {"wit_tool": "wit", "nkit_tool": "nkit", "dolphin_tool": "dolphin"}
WIT_EXE_NAME = "wit.exe" if IS_WINDOWS else "wit"
NKIT_EXE_NAME = "nkit.exe" if IS_WINDOWS else "nkit"
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
    "nkit_tool": [
        NKIT_EXE_NAME,
        r"C:\NKit\nkit.exe",
        r"C:\Program Files\NKit\nkit.exe",
    ],
}
# Start-up check arguments per tool (only used right after unpacking a download)
TOOL_SMOKE = {"wit_tool": ("--version",), "nkit_tool": ("-cfg", "n"), "dolphin_tool": ("--version",)}

def _tool_starts(exe: Path, args=()):
    """
    Start-up check after unpacking a download: does the binary launch at all?
    Returns (started, detail). Only a launch failure or a crash-style exit code
    (NTSTATUS, e.g. missing DLL 0xC0000135, blocked by antivirus) counts as
    "not started"; any ordinary exit code, including usage errors, is fine.
    """
    try:
        r = subprocess.run([str(exe), *args], capture_output=True, timeout=45,
                           cwd=str(exe.parent), stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return True, "still running after 45 s (assumed started)"
    except OSError as exc:
        return False, str(exc)
    code = r.returncode
    if code < 0 or code > 0xFFFF:
        out = (r.stderr or r.stdout or b"").decode("utf-8", "replace").strip()
        return False, f"exit code {code} (0x{code & 0xFFFFFFFF:08X}) {out[-300:]}".strip()
    return True, f"exit code {code}"

def _download_with_curl(url: str, tmp: Path) -> bool:
    """Fallback for a Python whose certificate store cannot verify the site: Windows 10+
    ships curl.exe, which uses the system certificate store."""
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        return False
    warn("Retrying the download with curl ...")
    try:
        r = subprocess.run([curl, "-L", "--fail", "--silent", "--show-error", "-o", str(tmp), url],
                           timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0

def _download(url: str, dest: Path, expected_sha256: str = ""):
    """Download url to dest with a progress line; verify sha256 when given."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        _download_urllib(url, tmp)
    except (urllib.error.URLError, OSError) as exc:
        if not (IS_WINDOWS and _download_with_curl(url, tmp)):
            raise
        warn(f"(urllib failed first: {exc})")
    digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
    if expected_sha256 and digest.lower() != expected_sha256.lower():
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"SHA-256 mismatch for {url}\n"
                           f"      expected {expected_sha256}\n"
                           f"      got      {digest}")
    tmp.replace(dest)

def _download_urllib(url: str, tmp: Path):
    req = urllib.request.Request(url, headers={"User-Agent": "WiiFormatConverter/1.1"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        t_last = 0.0
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
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

def _extract_subdir(zip_path: Path, subdir: str, target: Path):
    """Extract everything under <subdir>/ in the zip into target (flattened to target/).
    An empty subdir extracts the whole archive."""
    prefix = (subdir.strip("/").replace("\\", "/") + "/") if subdir.strip("/") else ""
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

def install_tool(key: str) -> Path:
    """Download an official build of wit / nkit and unpack it into tools/<name>/."""
    env = key.split("_")[0].upper()          # WIT / NKIT
    exe_name = TOOL_CANDIDATES[key][0]
    if os.environ.get(f"WII_CONV_{env}_URL"):  # test / advanced override
        url = os.environ[f"WII_CONV_{env}_URL"]
        sha = os.environ.get(f"WII_CONV_{env}_SHA256", "")
        subdir = os.environ.get(f"WII_CONV_{env}_SUBDIR", "")
    else:
        if not IS_WINDOWS:
            raise RuntimeError(f"Automatic download of {exe_name} is only available on Windows. "
                               f"Install it manually and set {key} in config.ini.")
        machine = platform.machine().upper()
        if machine in ("ARM64", "AARCH64") and "winarm64" in TOOL_DOWNLOADS[key]:
            arch = "winarm64"
        elif machine in ("X86", "I386", "I686") and "win32" in TOOL_DOWNLOADS[key]:
            arch = "win32"
        else:
            arch = "win64"
        url, sha, subdir = TOOL_DOWNLOADS[key][arch]

    tools_dir = _writable_dir(TOOLS_DIRS)
    if tools_dir is None:
        raise RuntimeError("No writable folder for tools (tried: "
                           + ", ".join(str(d) for d in TOOLS_DIRS) + ")")
    tool_dir = tools_dir / TOOL_SUBDIRS[key]
    tmp_dir = tools_dir / (TOOL_SUBDIRS[key] + ".unpacking")
    zip_path = tools_dir / Path(url.split("?")[0]).name

    info(f"Downloading {TOOL_LABELS[key]}")
    info(f"From : {url}")
    info(f"To   : {tool_dir}")
    _download(url, zip_path, sha)
    if sha:
        ok("Checksum verified (SHA-256)")
    shutil.rmtree(tmp_dir, ignore_errors=True)
    n = _extract_subdir(zip_path, subdir, tmp_dir)
    zip_path.unlink(missing_ok=True)
    # Only now replace the tool folder, so a crash while unpacking never leaves a half tool behind
    shutil.rmtree(tool_dir, ignore_errors=True)
    tmp_dir.replace(tool_dir)
    exe = tool_dir / exe_name
    if not exe.exists():   # exe somewhere deeper in the archive?
        found = [p for p in tool_dir.rglob(exe_name) if p.is_file()]
        if found:
            exe = found[0]
    if n == 0 or not exe.exists():
        raise RuntimeError(f"{exe_name} not found inside the downloaded archive")
    ok(f"Unpacked {n} file(s)")
    started, detail = _tool_starts(exe, TOOL_SMOKE[key])
    if started:
        ok(f"Ready: {exe}")
    else:
        # Do not block on this heuristic: the real run reports the actual error per file.
        warn(f"{exe.name} did not start cleanly during the check: {detail}")
        warn("Continuing anyway. If every conversion fails, check whether your antivirus "
             f"quarantined {exe.name} and allow it.")
    return exe

# ── Config ───────────────────────────────────────────────────────────────────
def _new_config():
    # interpolation=None: a '%' in a path or name_format must never be interpreted
    return configparser.ConfigParser(interpolation=None)

def _decode_text_file(raw: bytes) -> str:
    """Decode a text file saved by any Windows editor (UTF-8, UTF-8 BOM, UTF-16, ANSI)."""
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", "replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", "replace")

def load_config():
    cfg = _new_config()
    if not CONFIG_FILE.exists():
        info(f"config.ini not found - creating it with default settings: {CONFIG_FILE}")
        try:
            CONFIG_FILE.write_text(DEFAULT_CONFIG, encoding="utf-8")
        except OSError as exc:
            warn(f"Could not write config.ini ({exc}); continuing with built-in defaults.")
            cfg.read_string(DEFAULT_CONFIG)
            return cfg
    try:
        cfg.read_string(_decode_text_file(CONFIG_FILE.read_bytes()))
    except (configparser.Error, OSError, UnicodeError) as exc:
        warn(f"config.ini could not be read ({exc}); continuing with built-in defaults.")
        cfg = _new_config()
        cfg.read_string(DEFAULT_CONFIG)
    return cfg

def cfg_path(value: str) -> str:
    """Config values may be written with quotes or a trailing backslash; normalise them."""
    v = (value or "").strip().strip('"').strip("'").strip()
    while len(v) > 3 and v.endswith(("\\", "/")):
        v = v[:-1]
    return v

def resolve_tool(cfg, key, allow_download=True):
    """
    Locate a tool. Order: config.ini path -> next to the script/.exe ->
    .\\tools\\<name>\\ -> system PATH -> well-known install folders ->
    (wit only) automatic download.
    Returns (path, found).
    """
    exe_name = TOOL_CANDIDATES[key][0]
    raw = cfg_path(cfg.get("paths", key, fallback=""))
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

    sub = TOOL_SUBDIRS[key]
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

    if key in TOOL_DOWNLOADS and allow_download:
        warn(f"{exe_name} not found anywhere - downloading it now")
        try:
            return install_tool(key), True
        except (RuntimeError, OSError, urllib.error.URLError, zipfile.BadZipFile) as exc:
            error(f"Automatic download of {exe_name} failed: {exc}")
            if key == "wit_tool":
                error("Manual fix: download the cygwin64 zip from https://wit.wiimm.de/download.html,")
                error(f"unzip it, and copy the whole 'bin' folder contents to: {BASE_DIR / 'tools' / 'wit'}")
            else:
                error("Manual fix: download NKit_CLI_win-x64_*.zip from https://github.com/Nanook/NKit/releases,")
                error(f"and unzip it into: {BASE_DIR / 'tools' / 'nkit'}")
            error(f"(or set {key} in config.ini to the .exe)")

    return (configured or Path(exe_name)), False

def get_output_dir(cfg, fmt: str, override: str = None) -> Path:
    key = "output_rvz" if fmt == "rvz" else "output_wbfs"
    default = f".\\{fmt.upper()}"
    raw = cfg_path(override or cfg.get("output", key, fallback=default)) or default
    p = Path(raw)
    if not p.is_absolute():
        p = BASE_DIR / p
    p = p.resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p

# ── Disc headers ─────────────────────────────────────────────────────────────
WII_MAGIC = 0x5D1C9EA3   # big-endian at disc offset 0x18
GC_MAGIC = 0xC2339F3D    # big-endian at disc offset 0x1C
NKIT_MAGIC = b"NKIT"     # at disc offset 0x200 in NKit images (same check Dolphin uses)

def read_disc_header(path: Path):
    """
    Return {'id': 'RMGE01', 'title': '...', 'wii': bool, 'gc': bool, 'nkit': bool}
    for a plain .iso or a .wbfs file, or None if the header cannot be read / is not a disc.
    """
    nkit = False
    try:
        with open(path, "rb") as f:
            if path.suffix.lower() == ".wbfs":
                head = f.read(16)
                if len(head) < 16 or head[:4] != b"WBFS" or not 9 <= head[8] <= 16:
                    return None
                f.seek(1 << head[8])   # first disc header copy = second HD sector
                hdr = f.read(0x60)
            else:
                hdr = f.read(0x60)
                f.seek(0x200)
                nkit = f.read(4) == NKIT_MAGIC
    except Exception:          # OSError, OverflowError on garbage headers, ...
        return None
    if len(hdr) < 0x60:
        return None
    id6 = hdr[:6]
    if not all(0x30 <= b <= 0x5A or 0x61 <= b <= 0x7A for b in id6):
        return None
    disc = hdr[6]              # disc number: 0 for most games, 1 for disc 2 of a 2-disc game
    wii = struct.unpack(">I", hdr[0x18:0x1C])[0] == WII_MAGIC
    gc = struct.unpack(">I", hdr[0x1C:0x20])[0] == GC_MAGIC
    title = hdr[0x20:0x60].split(b"\0", 1)[0].decode("ascii", "replace").strip()
    gid = id6.decode("ascii")
    return {"id": gid, "key": gid if disc == 0 else f"{gid}#{disc + 1}", "disc": disc,
            "title": title, "wii": wii, "gc": gc, "nkit": nkit}

WII_SECTORS_PER_DISC = 143432 * 2   # 0x8000-byte sectors on a dual-layer Wii disc

def wbfs_expected_size(path: Path):
    """
    Minimum byte size a .wbfs file must have according to its own block table
    (highest used WBFS block + 1) * block size. None if the header is unreadable.
    Used to spot files that were truncated by a crash or an interrupted copy.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(16)
            if len(head) < 16 or head[:4] != b"WBFS" or not 9 <= head[8] <= 16 or not 16 <= head[9] <= 30:
                return None
            hd_sec_sz, wbfs_sec_sz = 1 << head[8], 1 << head[9]
            n_blocks = WII_SECTORS_PER_DISC * 0x8000 // wbfs_sec_sz
            f.seek(hd_sec_sz + 0x100)
            table = f.read(n_blocks * 2)
    except Exception:
        return None
    if len(table) < n_blocks * 2:
        return None
    max_used = max(struct.unpack(f">{n_blocks}H", table))
    if max_used == 0:
        return None
    return (max_used + 1) * wbfs_sec_sz

def wbfs_actual_size(path: Path) -> int:
    """Size of a .wbfs plus its split parts (.wbf1, .wbf2, ...)."""
    total = path.stat().st_size
    for i in range(1, 20):
        part = path.with_suffix(f".wbf{i}")
        if not part.exists():
            break
        total += part.stat().st_size
    return total

def wbfs_is_complete(path: Path) -> bool:
    """False when the file is clearly shorter than its block table says it must be."""
    try:
        if path.stat().st_size == 0:
            return False
        expected = wbfs_expected_size(path)
        if expected is None:
            return True      # cannot tell - assume fine
        return wbfs_actual_size(path) >= expected
    except OSError:
        return False

def is_nkit_image(path: Path, hdr=None) -> bool:
    """NKit images carry 'NKIT' at 0x200; the file name usually says so too."""
    if ".nkit." in path.name.lower():
        return True
    return bool(hdr and hdr.get("nkit"))

def index_existing_wbfs(out_dir: Path) -> dict:
    """Map game key (ID, plus disc number for multi-disc games) -> path for every
    complete .wbfs already under out_dir, whatever it is called."""
    index = {}
    try:
        for p in out_dir.rglob("*"):
            try:
                if not p.is_file() or p.suffix.lower() != ".wbfs":
                    continue
                if STAGING_NAME in p.parts:
                    continue
                hdr = read_disc_header(p)
                if not hdr:
                    continue
                if not wbfs_is_complete(p):
                    exp = wbfs_expected_size(p) or 0
                    warn(f"Ignoring {p.name}: looks truncated "
                         f"({wbfs_actual_size(p) / 1_048_576:,.0f} of {exp / 1_048_576:,.0f} MB), "
                         "it will be converted again")
                    index.setdefault("truncated:" + hdr["key"], p)
                    continue
                index.setdefault(hdr["key"], p)
            except OSError:
                continue
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
    if stem.lower().endswith(".nkit"):      # "Game (USA).nkit.iso" -> "Game (USA)"
        stem = stem[:-5]
    if not hdr:
        return stem
    if hdr["id"] in stem.upper():          # already named like "Title [RMGE01]" or "RMGE01"
        return stem
    try:
        name = name_format.format(name=stem, id=hdr["id"], title=hdr["title"] or stem)
    except Exception:
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
def _quote_arg(a) -> str:
    """Quote one argument for the Windows command line (MS C runtime rules), always."""
    a = str(a)
    out, bs = [], 0
    for ch in a:
        if ch == "\\":
            bs += 1
            continue
        if ch == '"':
            out.append("\\" * (bs * 2 + 1) + '"')
            bs = 0
            continue
        if bs:
            out.append("\\" * bs)
            bs = 0
        out.append(ch)
    if bs:
        out.append("\\" * (bs * 2))
    return '"' + "".join(out) + '"'

def _cmd_for_subprocess(cmd: list):
    """On Windows pass a fully quoted command line: cygwin programs (wit) parse it
    themselves and would otherwise trip over an unquoted apostrophe or glob character."""
    if IS_WINDOWS:
        return " ".join(_quote_arg(c) for c in cmd)
    return [str(c) for c in cmd]

def _crash_hint(cmd: list, code: int):
    if code < 0 or code > 0xFFFF:
        exe = Path(str(cmd[0]))
        error(f"{exe.name} crashed or could not load (code 0x{code & 0xFFFFFFFF:08X}). "
              "Usually a missing DLL or an antivirus block.")
        for t in TOOLS_DIRS:
            if t in exe.parents:
                error(f"Delete the folder {exe.parent} and run again to re-download it.")

def run_cmd(cmd: list, desc: str) -> bool:
    info(f"Command: {' '.join(str(c) for c in cmd)}")
    print()
    t0 = time.time()
    try:
        result = subprocess.run(_cmd_for_subprocess(cmd))
    except OSError as exc:
        error(f"{desc} could not start: {exc}")
        return False
    elapsed = time.time() - t0
    _enable_ansi()   # cygwin programs (wit) reset the console mode when they exit
    if result.returncode != 0:
        error(f"{desc} failed (exit code {result.returncode})")
        _crash_hint(cmd, result.returncode)
        return False
    ok(f"{desc} completed in {elapsed:.1f}s")
    return True

def run_cmd_code(cmd: list, desc: str) -> int:
    """Like run_cmd but returns the exit code (-1 if it could not start). stdin is closed
    so a tool that asks a question fails instead of waiting forever."""
    info(f"Command: {' '.join(str(c) for c in cmd)}")
    print()
    t0 = time.time()
    try:
        result = subprocess.run(_cmd_for_subprocess(cmd), stdin=subprocess.DEVNULL)
    except OSError as exc:
        error(f"{desc} could not start: {exc}")
        return -1
    _enable_ansi()
    elapsed = time.time() - t0
    if result.returncode == 0:
        ok(f"{desc} completed in {elapsed:.1f}s")
    else:
        warn(f"{desc} exited with code {result.returncode} after {elapsed:.1f}s")
        _crash_hint(cmd, result.returncode)
    return result.returncode

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

BATCH_WARNINGS = []   # (file name, message) collected for the batch summary

def _largest(files):
    return max(files, key=lambda p: p.stat().st_size)

def nkit_run(nkit: Path, source: Path, work_dir: Path, task: str, want_ext: str,
             convert_fmt: str = None):
    """
    Run NKit on one image with a throw-away work folder.
    Returns (exit_code, [produced files with want_ext]).
    NKit exit codes: 0 ok, 1 finished but reported a problem (e.g. verification),
    2 bad parameters, 3 config error, 6 unknown error, 7 cancelled.
    """
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(nkit), "-cfg", "n", "-task", task,
           "-in", str(source), "-out", str(work_dir), "-tmp", str(work_dir),
           "-r", "n", "-arc", "n", "-results", "n", "-consoleLevel", "info"]
    if convert_fmt:
        cmd += ["-convert", convert_fmt]
    code = run_cmd_code(cmd, f"nkit {task}")
    files = [p for p in work_dir.rglob("*")
             if p.is_file() and p.suffix.lower() == want_ext and p.stat().st_size > 0]
    return code, files

def convert_iso_to_wbfs(source: Path, cfg, wit: Path, out_dir: Path = None,
                        skip_existing: bool = False, existing_index: dict = None,
                        name_format: str = "{name}", split: bool = False,
                        nkit: Path = None, nkit_mode: str = "wbfs"):
    """
    ISO -> WBFS. The original ISO is NOT deleted.
    Writes into <out_dir>/.incomplete/ first and moves the result into place
    only when the conversion succeeds, so an interrupted run never leaves a
    file that looks finished.
    NKit images are converted with NKit (directly to WBFS, or expanded to a
    full ISO and then passed to wit), because wit cannot read them.
    Returns True (converted), False (failed) or None (skipped).
    """
    if out_dir is None:
        out_dir = get_output_dir(cfg, "wbfs")
    hdr = read_disc_header(source)
    base = wbfs_name_for(source, hdr, name_format)
    dest = out_dir / (base + ".wbfs")
    nkit_img = is_nkit_image(source, hdr)

    if hdr:
        kind = "Wii" if hdr["wii"] else ("GameCube" if hdr["gc"] else "unknown type")
        info(f"Disc   : {hdr['id']}  {hdr['title']}  ({kind}{', NKit image' if nkit_img else ''})")
        if not hdr["wii"] and not hdr["gc"]:
            warn("Header has no Wii/GameCube magic - this may not be a disc image")
    else:
        warn("Could not read a disc header - is this really a Wii ISO?")

    key = hdr["key"] if hdr else None
    same_game = existing_index.get(key) if (existing_index and key) else None
    if skip_existing:
        if dest.exists():
            if wbfs_is_complete(dest):
                warn(f"Already exists, skipping: {dest.name}")
                return None
            warn(f"{dest.name} exists but looks truncated - converting it again")
        elif same_game is not None:
            warn(f"Already converted as {same_game.name} "
                 f"(same game ID {hdr['id']}), skipping")
            return None

    # A WBFS is at most as large as its ISO, usually much smaller (unused blocks are dropped).
    free = shutil.disk_usage(out_dir).free
    if free < 512 * 1_048_576:
        error(f"Not enough free space on {out_dir.anchor or out_dir} ({free / 1_048_576:,.0f} MB free)")
        return False
    if free < source.stat().st_size:
        warn(f"Only {free / 1_073_741_824:.1f} GB free on {out_dir.anchor or out_dir}; "
             "the conversion will fail if the WBFS does not fit")

    stage_dir = out_dir / STAGING_NAME
    stage_dir.mkdir(parents=True, exist_ok=True)
    # Work under a plain name: wit treats '%' in a destination name as an escape sequence
    # and cygwin has its own quoting rules. The finished file is renamed to dest afterwards.
    plain = re.sub(r"[^A-Za-z0-9._ \[\]()-]", "_", dest.stem)[:120] or "game"
    staged = stage_dir / (plain + ".wbfs")
    split_args = ["--split"] if split else []   # wit picks a FAT-safe part size itself

    if nkit_img:
        info("NKit image: wit cannot read these, NKit restores it first")
        if nkit is None:
            error("nkit.exe is not available (see the messages above) - cannot convert this NKit image")
            return False
        work = stage_dir / (safe_filename(base) + ".nkit-work")
        success = False
        try:
            if nkit_mode != "iso":
                step(1, "NKit image -> WBFS (nkit)")
                info(f"Source : {source}")
                info(f"Dest   : {dest}")
                code, files = nkit_run(nkit, source, work, "convert", ".wbfs", "wbfs")
                if files and code in (0, 1):
                    produced = _largest(files)
                    if staged.exists():
                        staged.unlink()
                    shutil.move(str(produced), str(staged))
                    if code == 1:
                        warn("NKit finished but reported a problem (verification?) - the WBFS was kept")
                        BATCH_WARNINGS.append((source.name, "NKit reported a problem, output kept"))
                    success = True
                else:
                    warn("Direct NKit -> WBFS did not work, trying NKit -> full ISO -> wit")
            if not success:
                full_iso = 4_800 * 1_048_576   # a full single-layer Wii ISO is 4.38 GiB
                free = shutil.disk_usage(out_dir).free
                if free < full_iso:
                    error(f"Not enough free space on {out_dir.anchor or out_dir} for the temporary "
                          f"full ISO ({free / 1_073_741_824:.1f} GB free, about "
                          f"{full_iso / 1_073_741_824:.1f} GB needed)")
                    return False
                step(1, "NKit image -> full ISO (nkit, temporary file)")
                info(f"Source : {source}")
                info(f"Work   : {work}")
                code, files = nkit_run(nkit, source, work, "expand", ".iso")
                if not files or code not in (0, 1):
                    error(f"NKit could not restore this image (exit code {code})")
                    return False
                iso_tmp = _largest(files)
                if code == 1:
                    warn("NKit finished but reported a problem (verification?) - continuing with the restored ISO")
                    BATCH_WARNINGS.append((source.name, "NKit reported a problem, output kept"))
                step(2, "ISO -> WBFS (wit)")
                info(f"Temp ISO : {iso_tmp}")
                info(f"Dest     : {dest}")
                success = run_cmd([str(wit), "copy", str(iso_tmp), str(staged),
                                   "--wbfs", "--overwrite", *split_args], "ISO -> WBFS")
        finally:
            shutil.rmtree(work, ignore_errors=True)
    else:
        step(1, "ISO -> WBFS (wit)")
        info(f"Source : {source}")
        info(f"Dest   : {dest}")
        success = run_cmd([str(wit), "copy", str(source), str(staged),
                           "--wbfs", "--overwrite", *split_args], "ISO -> WBFS")

    # Everything produced for this game (name.wbfs, and name.wbf1... when split)
    parts = sorted(p for p in stage_dir.iterdir()
                   if p.is_file() and p.stem == staged.stem)
    if not success:
        for p in parts:
            p.unlink(missing_ok=True)
        if parts:
            warn("Removed partial output")
        return False
    if not parts or not staged.exists() or staged.stat().st_size == 0:
        error("The converter reported success but produced no output file")
        for p in parts:
            p.unlink(missing_ok=True)
        return False

    # Remove stale copies of this game before moving the new one into place
    for p in parts:
        old = out_dir / (dest.stem + p.suffix)
        if old.exists():
            old.unlink()
    stale = [(same_game, "Replaced the older copy")]
    if existing_index and key:
        stale.append((existing_index.pop("truncated:" + key, None), "Removed the truncated copy"))
    for old, msg in stale:
        if old is None or not old.exists() or old.resolve() == dest.resolve():
            continue
        try:
            for i in range(1, 20):
                part = old.with_suffix(f".wbf{i}")
                if part.exists():
                    part.unlink()
            old.unlink()
            warn(f"{msg} {old.name}")
        except OSError as exc:
            warn(f"Could not remove {old}: {exc}")

    for p in parts:
        shutil.move(str(p), str(out_dir / (dest.stem + p.suffix)))

    step("*", "Result")
    ok(f"Created file: {dest}")
    if len(parts) > 1:
        ok(f"Split into {len(parts)} parts (FAT32 4 GB limit)")
    ok(f"Original ISO preserved: {source}")
    if dest.exists():
        print_sizes(source, dest)
    if existing_index is not None and key:
        existing_index[key] = dest
    return True

def optional_tool(cfg, key, label, allow_download):
    """Like require_tool but returns None instead of exiting when the tool is missing."""
    tool, found = resolve_tool(cfg, key, allow_download=allow_download)
    if not found:
        error(f"{label} not found: {tool}")
        return None
    ok(f"{label:<11} : {tool}")
    return tool

def batch_iso_to_wbfs(in_dir: Path, out_dir: Path, cfg, wit: Path,
                      overwrite: bool = False, allow_download: bool = True) -> bool:
    """Convert every .iso under in_dir to .wbfs in out_dir. Returns True if nothing failed."""
    name_format = cfg.get("batch", "name_format", fallback="{name} [{id}]").strip() or "{name}"
    nkit_mode = cfg.get("batch", "nkit_mode", fallback="wbfs").strip().lower() or "wbfs"
    if "{id}" not in name_format:
        warn(f"name_format '{name_format}' has no {{id}}: two different games with the same "
             "name would overwrite each other")
    out_res = out_dir.resolve()
    clean_staging(out_dir)

    isos = []
    for p in sorted(in_dir.rglob("*")):
        try:
            if not p.is_file() or p.suffix.lower() != ".iso":
                continue
            if STAGING_NAME in p.parts or p.parent.resolve() == out_res:
                continue  # never treat this tool's own output as input
        except OSError:
            continue
        isos.append(p)

    if not isos:
        warn(f"No .iso files found in: {in_dir}")
        warn("Put your Wii ISO files in that folder and run this again.")
        return True

    fs = filesystem_name(out_dir)
    split = fs is not None and fs.upper().startswith("FAT")   # FAT / FAT32: 4 GB file limit
    if fs:
        info(f"Output filesystem: {fs}" + ("  -> large games will be split at 4 GB" if split else ""))

    existing = index_existing_wbfs(out_dir)   # with --overwrite: used to replace older copies
    if existing:
        info(f"{len(existing)} game(s) already present in {out_dir}")

    nkit_count = sum(1 for p in isos if is_nkit_image(p, read_disc_header(p)))
    nkit = None
    if nkit_count:
        info(f"{nkit_count} of {len(isos)} file(s) are NKit images (*.nkit.iso) - NKit is needed for those")
        nkit = optional_tool(cfg, "nkit_tool", "NKit", allow_download)
        if nkit is None:
            warn("NKit images will be reported as failed; plain ISOs are still converted")

    info(f"Found {len(isos)} ISO file(s) in {in_dir}")
    print()
    converted, skipped, failed = [], [], []
    BATCH_WARNINGS.clear()
    t0 = time.time()

    for i, iso in enumerate(isos, 1):
        try:
            size_mb = iso.stat().st_size / 1_048_576
        except OSError:
            print(f"\n{BOLD}{CYAN}=== [{i}/{len(isos)}] {iso.name} ==={RESET}")
            error("File disappeared while the batch was running - skipped")
            failed.append(iso.name)
            continue
        print(f"\n{BOLD}{CYAN}=== [{i}/{len(isos)}] {iso.name} ({size_mb:,.1f} MB) ==={RESET}")
        try:
            res = convert_iso_to_wbfs(iso, cfg, wit, out_dir=out_dir,
                                      skip_existing=not overwrite,
                                      existing_index=existing,
                                      name_format=name_format, split=split,
                                      nkit=nkit, nkit_mode=nkit_mode)
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
    if BATCH_WARNINGS:
        warn(f"Warnings  : {len(BATCH_WARNINGS)}")
        for name, msg in BATCH_WARNINGS:
            warn(f"   - {name}: {msg}")
    if failed:
        error(f"Failed    : {len(failed)}")
        for name in failed:
            error(f"   - {name}")
        if nkit_count and nkit is None:
            error("NKit images could not be converted because nkit.exe is missing (see above).")
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
                        help="Never download wit.exe / nkit.exe automatically.")
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
        in_raw = cfg_path(args.batch or cfg.get("batch", "input_iso", fallback=""))
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

        out_override = cfg_path(args.output or cfg.get("batch", "output_wbfs", fallback="")) or None
        try:
            out_dir = get_output_dir(cfg, "wbfs", override=out_override)
        except OSError as exc:
            fail(f"Output folder could not be created: {out_override} ({exc})")
        ok(f"Output dir : {out_dir}")
        if out_dir == in_dir:
            fail("Input and output folder are the same - choose a different output folder.")

        step(1, "Checking tools")
        wit = require_tool(cfg, "wit_tool", "WIT", allow_download)

        success = batch_iso_to_wbfs(in_dir, out_dir, cfg, wit, overwrite=args.overwrite,
                                    allow_download=allow_download)
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

    try:
        out_dir = get_output_dir(cfg, fmt_dest, override=args.output)
    except OSError as exc:
        fail(f"Output folder could not be created ({exc}). Check output_{fmt_dest} in config.ini "
             "or pass --output.")
    ok(f"Output dir : {out_dir}")
    if fmt_dest == "wbfs":
        clean_staging(out_dir)

    # ── Conversion ──────────────────────────────────────────────────────────
    if ext == ".wbfs":
        success = convert_wbfs_to_rvz(source, cfg, dolphin, wit, out_dir=out_dir)
    elif ext == ".rvz":
        success = convert_rvz_to_wbfs(source, cfg, dolphin, wit, out_dir=out_dir)
    elif ext == ".iso" and iso_target_fmt == "rvz":
        if is_nkit_image(source, read_disc_header(source)):
            warn("This is an NKit image: DolphinTool will produce an NKit-based RVZ, not a full one.")
        success = convert_iso_to_rvz(source, cfg, dolphin, out_dir=out_dir)
    else:
        name_format = cfg.get("batch", "name_format", fallback="{name} [{id}]").strip() or "{name}"
        nkit_mode = cfg.get("batch", "nkit_mode", fallback="wbfs").strip().lower() or "wbfs"
        fs = filesystem_name(out_dir)
        split = fs is not None and fs.upper().startswith("FAT")
        nkit = None
        if is_nkit_image(source, read_disc_header(source)):
            info("This is an NKit image - NKit is needed to restore it")
            nkit = optional_tool(cfg, "nkit_tool", "NKit", allow_download)
        success = convert_iso_to_wbfs(source, cfg, wit, out_dir=out_dir,
                                      name_format=name_format, split=split,
                                      nkit=nkit, nkit_mode=nkit_mode)

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
