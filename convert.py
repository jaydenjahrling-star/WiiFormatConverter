#!/usr/bin/env python3
"""
Wii Image Converter - RVZ <-> WBFS <-> ISO
Drag and drop a .rvz, .wbfs, or .iso file onto this script.

Flows:
WBFS -> RVZ : WIT (WBFS->temporary ISO) + DolphinTool (ISO->RVZ) + temporary ISO cleanup
RVZ -> WBFS : DolphinTool (RVZ->temporary ISO) + WIT (ISO->WBFS) + temporary ISO cleanup
ISO -> RVZ : direct DolphinTool conversion (original ISO is NOT deleted)
ISO -> WBFS : direct WIT conversion (original ISO is NOT deleted)
"""

import sys
import subprocess
import configparser
import time
import tempfile
import shutil
import ctypes
from pathlib import Path

# ── ANSI colors ──────────────────────────────────────────────────────────────
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

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

DEFAULT_CONFIG = """\
[paths]
dolphin_tool = C:\\Dolphin\\DolphinTool.exe
wit_tool = C:\\WiimmsISOTools\\wit.exe

[output]
output_rvz = .\\RVZ
output_wbfs = .\\WBFS

[conversion]
rvz_compression = zstd
rvz_compression_level = 5
"""

# ── Native Windows dialog ────────────────────────────────────────────────────
def ask_format_dialog(filename: str) -> str:
    """
    Show a native Windows dialog with two buttons: RVZ and WBFS.
    Returns 'rvz' or 'wbfs'. If closed/cancelled, exits the program.
    Uses a MessageBox with Yes/No buttons mapped to RVZ/WBFS.
    """
    MB_YESNO = 0x00000004
    MB_ICONQUESTION = 0x00000020
    IDYES = 6
    IDNO = 7

    msg = (f"ISO file detected:\n{filename}\n\n"
           f"Which format do you want to convert it to?\n\n"
           f" [Yes] -> RVZ\n"
           f" [No] -> WBFS")
    title = "Wii Converter - Choose output format"

    result = ctypes.windll.user32.MessageBoxW(
        0, msg, title, MB_YESNO | MB_ICONQUESTION
    )

    if result == IDYES:
        return "rvz"
    elif result == IDNO:
        return "wbfs"
    else:
        warn("Dialog closed without a selection. Exiting.")
        sys.exit(0)

# ── Config ───────────────────────────────────────────────────────────────────
def load_config():
    if not CONFIG_FILE.exists():
        info(f"config.ini not found - creating the default file in: {CONFIG_FILE}")
        CONFIG_FILE.write_text(DEFAULT_CONFIG, encoding="utf-8")
        warn("Open config.ini and set the paths to DolphinTool.exe and wit.exe!")
        input("\nPress ENTER to exit...")
        sys.exit(1)
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_FILE, encoding="utf-8")
    return cfg

def resolve_tool(cfg, key):
    raw = cfg.get("paths", key, fallback="").strip()
    p = Path(raw)
    if not p.is_absolute():
        p = BASE_DIR / p
    p = p.resolve()
    return (p, True) if p.exists() else (p, False)

def get_output_dir(cfg, fmt: str) -> Path:
    key = "output_rvz" if fmt == "rvz" else "output_wbfs"
    default = f".\\{fmt.upper()}"
    raw = cfg.get("output", key, fallback=default).strip()
    p = Path(raw)
    if not p.is_absolute():
        p = BASE_DIR / p
    p = p.resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p

# ── Utilities ────────────────────────────────────────────────────────────────
def run_cmd(cmd: list, desc: str) -> bool:
    info(f"Command: {' '.join(str(c) for c in cmd)}")
    print()
    t0 = time.time()
    result = subprocess.run(cmd)
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

# ── Conversions ──────────────────────────────────────────────────────────────
def convert_wbfs_to_rvz(source: Path, cfg, dolphin: Path, wit: Path):
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

def convert_rvz_to_wbfs(source: Path, cfg, dolphin: Path, wit: Path):
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

def convert_iso_to_rvz(source: Path, cfg, dolphin: Path):
    """The original ISO is NOT deleted."""
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

def convert_iso_to_wbfs(source: Path, cfg, wit: Path):
    """The original ISO is NOT deleted."""
    out_dir = get_output_dir(cfg, "wbfs")
    dest = out_dir / (source.stem + ".wbfs")

    step(1, "ISO -> WBFS (wit)")
    info(f"Source : {source}")
    info(f"Dest   : {dest}")
    if not run_cmd([
        str(wit), "copy", str(source), str(dest),
        "--wbfs", "--overwrite",
    ], "ISO -> WBFS"):
        return False

    step(2, "Result")
    ok(f"Created file: {dest}")
    ok(f"Original ISO preserved: {source}")
    if dest.exists():
        print_sizes(source, dest)
    return True

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    print(f"\n{BOLD}{CYAN}=========================================={RESET}")
    print(f"{BOLD}{CYAN} Wii Converter | RVZ <-> WBFS <-> ISO{RESET}")
    print(f"{BOLD}{CYAN}=========================================={RESET}\n")

    if len(sys.argv) < 2:
        warn("No file specified.")
        warn("Drag and drop a .rvz, .wbfs, or .iso file onto the script or the .exe.")
        input("\nPress ENTER to exit...")
        sys.exit(1)

    source = Path(sys.argv[1]).resolve()

    step(0, "Checking source file")
    if not source.exists():
        error(f"File not found: {source}")
        input("\nPress ENTER to exit...")
        sys.exit(1)

    ext = source.suffix.lower()
    if ext not in (".rvz", ".wbfs", ".iso"):
        error(f"Unsupported format: '{ext}'")
        error("Supported formats: .rvz .wbfs .iso")
        input("\nPress ENTER to exit...")
        sys.exit(1)

    ok(f"File : {source.name} ({source.stat().st_size / 1_048_576:,.1f} MB)")
    ok(f"Base : {BASE_DIR}")

    cfg = load_config()

    dolphin, found = resolve_tool(cfg, "dolphin_tool")
    if not found:
        error(f"DolphinTool.exe not found: {dolphin}")
        error("Edit 'dolphin_tool' in config.ini.")
        input("\nPress ENTER to exit...")
        sys.exit(1)
    ok(f"DolphinTool : {dolphin}")

    wit, found = resolve_tool(cfg, "wit_tool")
    if not found:
        error(f"wit.exe not found: {wit}")
        error("Edit 'wit_tool' in config.ini.")
        input("\nPress ENTER to exit...")
        sys.exit(1)
    ok(f"WIT : {wit}")

    # ── Output format selection for ISO ────────────────────────────────────
    iso_target_fmt = None
    if ext == ".iso":
        iso_target_fmt = ask_format_dialog(source.name)
        info(f"Selected format: {iso_target_fmt.upper()}")

    fmt_dest = {
        ".wbfs": "rvz",
        ".rvz": "wbfs",
        ".iso": iso_target_fmt,
    }[ext]

    out_dir = get_output_dir(cfg, fmt_dest)
    ok(f"Output dir : {out_dir}")

    # ── Conversion ──────────────────────────────────────────────────────────
    if ext == ".wbfs":
        success = convert_wbfs_to_rvz(source, cfg, dolphin, wit)
    elif ext == ".rvz":
        success = convert_rvz_to_wbfs(source, cfg, dolphin, wit)
    elif ext == ".iso" and iso_target_fmt == "rvz":
        success = convert_iso_to_rvz(source, cfg, dolphin)
    elif ext == ".iso" and iso_target_fmt == "wbfs":
        success = convert_iso_to_wbfs(source, cfg, wit)

    print()
    if success:
        print(f"{BOLD}{GREEN}OK Conversion completed successfully!{RESET}")
    else:
        print(f"{BOLD}{RED}XX Conversion failed. Check the messages above.{RESET}")

    input("\nPress ENTER to close...")
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
