#!/usr/bin/env python3
"""
Wii Image Converter - RVZ <-> WBFS <-> ISO
Drag and drop a .rvz, .wbfs, or .iso file onto this script, or run it in
batch mode to convert a whole folder:

    python convert.py --batch "D:\Wii\ISO" --to wbfs --output "D:\Wii\wbfs"

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
import argparse
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
NO_PAUSE = "--no-pause" in sys.argv

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

[batch]
input_iso = D:\\Wii\\ISO
output_wbfs = D:\\Wii\\wbfs
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
        if not NO_PAUSE:
            input("\nPress ENTER to exit...")
        sys.exit(1)
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_FILE, encoding="utf-8")
    return cfg

TOOL_CANDIDATES = {
    "dolphin_tool": [
        "DolphinTool.exe",
        r"C:\Dolphin\DolphinTool.exe",
        r"C:\Program Files\Dolphin\DolphinTool.exe",
        r"C:\Program Files (x86)\Dolphin\DolphinTool.exe",
    ],
    "wit_tool": [
        "wit.exe",
        r"C:\WiimmsISOTools\wit.exe",
        r"C:\WiimmsISOTools\bin\wit.exe",
        r"C:\Program Files\Wiimm\WIT\wit.exe",
        r"C:\Program Files (x86)\Wiimm\WIT\wit.exe",
        r"C:\wit\wit.exe",
        r"C:\wit\bin\wit.exe",
    ],
}

def resolve_tool(cfg, key):
    """
    Locate a tool. Order: config.ini path -> next to the script/.exe ->
    system PATH -> well-known install folders.
    Returns (path, found).
    """
    raw = cfg.get("paths", key, fallback="").strip()
    if raw:
        p = Path(raw)
        if not p.is_absolute():
            p = BASE_DIR / p
        p = p.resolve()
        if p.exists():
            return p, True
    else:
        p = None

    exe_name = TOOL_CANDIDATES[key][0]
    local = BASE_DIR / exe_name
    if local.exists():
        return local.resolve(), True

    on_path = shutil.which(exe_name) or shutil.which(Path(exe_name).stem)
    if on_path:
        return Path(on_path).resolve(), True

    for cand in TOOL_CANDIDATES[key][1:]:
        c = Path(cand)
        if c.exists():
            return c.resolve(), True

    return (p if p is not None else Path(raw or exe_name)), False

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
                        skip_existing: bool = False):
    """The original ISO is NOT deleted."""
    if out_dir is None:
        out_dir = get_output_dir(cfg, "wbfs")
    dest = out_dir / (source.stem + ".wbfs")

    if skip_existing and dest.exists() and dest.stat().st_size > 0:
        warn(f"Already exists, skipping: {dest.name}")
        return None

    step(1, "ISO -> WBFS (wit)")
    info(f"Source : {source}")
    info(f"Dest   : {dest}")
    if not run_cmd([
        str(wit), "copy", str(source), str(dest),
        "--wbfs", "--overwrite",
    ], "ISO -> WBFS"):
        # Do not leave a half-written file behind; it would be skipped next run.
        if dest.exists():
            dest.unlink(missing_ok=True)
            warn(f"Removed partial output: {dest.name}")
        return False

    step(2, "Result")
    ok(f"Created file: {dest}")
    ok(f"Original ISO preserved: {source}")
    if dest.exists():
        print_sizes(source, dest)
    return True

def batch_iso_to_wbfs(in_dir: Path, out_dir: Path, cfg, wit: Path,
                      overwrite: bool = False) -> bool:
    """Convert every .iso in in_dir to .wbfs in out_dir. Returns True if nothing failed."""
    isos = sorted(p for p in in_dir.iterdir()
                  if p.is_file() and p.suffix.lower() == ".iso")
    if not isos:
        warn(f"No .iso files found in: {in_dir}")
        return True

    info(f"Found {len(isos)} ISO file(s) in {in_dir}")
    print()
    converted, skipped, failed = [], [], []
    t0 = time.time()

    for i, iso in enumerate(isos, 1):
        print(f"\n{BOLD}{CYAN}=== [{i}/{len(isos)}] {iso.name} "
              f"({iso.stat().st_size / 1_048_576:,.1f} MB) ==={RESET}")
        try:
            res = convert_iso_to_wbfs(iso, cfg, wit, out_dir=out_dir,
                                      skip_existing=not overwrite)
        except Exception as exc:  # keep going with the rest of the folder
            error(f"Unexpected error: {exc}")
            res = False
        if res is None:
            skipped.append(iso.name)
        elif res:
            converted.append(iso.name)
        else:
            failed.append(iso.name)

    elapsed = time.time() - t0
    print(f"\n{BOLD}{CYAN}=========== Batch summary ==========={RESET}")
    ok(f"Converted : {len(converted)}")
    warn(f"Skipped   : {len(skipped)} (already in {out_dir})")
    if failed:
        error(f"Failed    : {len(failed)}")
        for name in failed:
            error(f"   - {name}")
    else:
        ok(f"Failed    : 0")
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
    parser.add_argument("--batch", metavar="FOLDER",
                        help="Convert every .iso in FOLDER (batch mode). "
                             "Defaults to [batch] input_iso from config.ini "
                             "when given without a value.",
                        nargs="?", const="")
    parser.add_argument("--to", choices=["rvz", "wbfs"],
                        help="Target format for ISO input. Skips the Yes/No dialog.")
    parser.add_argument("--output", metavar="FOLDER",
                        help="Output folder. Overrides config.ini.")
    parser.add_argument("--overwrite", action="store_true",
                        help="Batch mode: re-convert files that already exist in the output folder.")
    parser.add_argument("--no-pause", action="store_true",
                        help="Do not wait for ENTER before exiting.")
    return parser.parse_args(argv)

def pause(args, msg="\nPress ENTER to exit..."):
    if not args.no_pause:
        input(msg)

def require_tool(cfg, key, label, args):
    tool, found = resolve_tool(cfg, key)
    if not found:
        error(f"{label} not found: {tool}")
        error(f"Edit '{key}' in config.ini.")
        pause(args)
        sys.exit(1)
    ok(f"{label:<11} : {tool}")
    return tool

def main():
    print(f"\n{BOLD}{CYAN}=========================================={RESET}")
    print(f"{BOLD}{CYAN} Wii Converter | RVZ <-> WBFS <-> ISO{RESET}")
    print(f"{BOLD}{CYAN}=========================================={RESET}\n")

    args = parse_args(sys.argv[1:])

    # ── Batch mode: folder of ISOs -> WBFS ─────────────────────────────────
    if args.batch is not None:
        if args.to and args.to != "wbfs":
            error("Batch mode currently supports ISO -> WBFS only (--to wbfs).")
            pause(args)
            sys.exit(1)

        cfg = load_config()
        in_raw = args.batch or cfg.get("batch", "input_iso", fallback="").strip()
        if not in_raw:
            error("No input folder. Use --batch <folder> or set [batch] input_iso in config.ini.")
            pause(args)
            sys.exit(1)
        in_dir = Path(in_raw).resolve()

        step(0, "Checking input folder")
        if not in_dir.is_dir():
            error(f"Folder not found: {in_dir}")
            pause(args)
            sys.exit(1)
        ok(f"Input dir  : {in_dir}")
        ok(f"Base       : {BASE_DIR}")

        out_override = args.output or cfg.get("batch", "output_wbfs", fallback="").strip() or None
        out_dir = get_output_dir(cfg, "wbfs", override=out_override)
        ok(f"Output dir : {out_dir}")

        wit = require_tool(cfg, "wit_tool", "WIT", args)

        success = batch_iso_to_wbfs(in_dir, out_dir, cfg, wit, overwrite=args.overwrite)
        print()
        if success:
            print(f"{BOLD}{GREEN}OK Batch conversion completed successfully!{RESET}")
        else:
            print(f"{BOLD}{RED}XX Some conversions failed. Check the messages above.{RESET}")
        pause(args, "\nPress ENTER to close...")
        sys.exit(0 if success else 1)

    # ── Single-file mode ───────────────────────────────────────────────────
    if not args.source:
        warn("No file specified.")
        warn("Drag and drop a .rvz, .wbfs, or .iso file onto the script or the .exe,")
        warn('or run in batch mode:  convert.py --batch "D:\\Wii\\ISO" --to wbfs --output "D:\\Wii\\wbfs"')
        pause(args)
        sys.exit(1)

    source = Path(args.source).resolve()

    step(0, "Checking source file")
    if not source.exists():
        error(f"File not found: {source}")
        pause(args)
        sys.exit(1)

    ext = source.suffix.lower()
    if ext not in (".rvz", ".wbfs", ".iso"):
        error(f"Unsupported format: '{ext}'")
        error("Supported formats: .rvz .wbfs .iso")
        pause(args)
        sys.exit(1)

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
    dolphin = require_tool(cfg, "dolphin_tool", "DolphinTool", args) if needs_dolphin else None
    wit = require_tool(cfg, "wit_tool", "WIT", args) if needs_wit else None

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
        success = convert_iso_to_wbfs(source, cfg, wit, out_dir=out_dir)

    print()
    if success:
        print(f"{BOLD}{GREEN}OK Conversion completed successfully!{RESET}")
    else:
        print(f"{BOLD}{RED}XX Conversion failed. Check the messages above.{RESET}")

    pause(args, "\nPress ENTER to close...")
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
