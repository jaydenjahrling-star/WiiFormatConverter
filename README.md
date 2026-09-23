# Wii Converter — RVZ ↔ WBFS ↔ ISO

A simple Windows tool to convert Wii disc image files between **RVZ**, **WBFS**, and **ISO** formats using **DolphinTool** and **WIT**.

It supports **drag & drop**, a **one-click batch mode** (`iso_to_wbfs.bat`), and works with both the Python script and the precompiled Windows release.

---

## Quick start: `D:\Wii\ISO` → `D:\Wii\wbfs` in one click

1. Put your `.iso` files in `D:\Wii\ISO`.
2. Double-click **`iso_to_wbfs.bat`**.

That is all. The launcher takes care of the rest on a fresh Windows PC:

- **Python missing?** It is installed automatically with `winget` (Windows Package Manager). If that is not possible the Python download page opens with instructions.
- **`wit.exe` missing?** The official Wiimms ISO Tools build is downloaded into `tools\wit\`, checksum-verified, and used from there.
- **NKit images (`*.nkit.iso`)?** These are not real ISOs and WIT rejects them ("No valid source file found"). The converter detects them and restores them with NKit, which is downloaded into `tools\nkit\` the same way.
- **No `config.ini`?** One is created with these folders already filled in.
- **Ran it before / converted some games with another tool?** Games already in `D:\Wii\wbfs` are skipped, even if they were named differently, because the game ID inside the file is compared. Unfinished files from an interrupted run are cleaned up and redone.
- Output is named `Game Name [GAMEID].wbfs`, the naming Wii USB loaders recognise. On a FAT32 drive, games over 4 GB are split automatically.
- Original ISOs are never modified or deleted. A summary of converted / skipped / failed games is printed at the end.

---

## Features

- Convert **WBFS → RVZ**
- Convert **RVZ → WBFS**
- Convert **ISO → RVZ**
- Convert **ISO → WBFS**
- **One-click batch mode**: convert a whole folder of ISOs to WBFS (`iso_to_wbfs.bat`) — installs Python and downloads WIT by itself when they are missing
- Skips games that are already converted (matched by game ID, not just file name) and cleans up interrupted conversions
- Converts **NKit images** (`*.nkit.iso`) too, using NKit 2 (downloaded automatically)
- Loader-friendly output names (`Title [GAMEID].wbfs`) and automatic 4 GB splitting on FAT32 drives
- Drag & drop support on Windows
- Native Windows prompt for choosing the target format when an **ISO** file is dropped
- Separate output folders for **RVZ** and **WBFS**
- Configurable RVZ compression settings
- Temporary files are removed automatically when needed

---

## Repository contents

```text
WiiConverter/
├── convert.py              ← main Python script
├── convert.bat             ← drag & drop launcher (Windows)
├── iso_to_wbfs.bat         ← one-click batch launcher: D:\Wii\ISO → D:\Wii\wbfs
├── config.sample.ini       ← sample configuration file
├── version_info.txt        ← Windows version metadata for the .exe
├── WiiFormatExchanger.ico  ← application icon
├── LICENSE                 ← MIT license
└── README.md               ← this file
```

---

## Precompiled release

If you just want to use the program on Windows, download the precompiled build from the **Releases** section of this repository.

The release archive contains a ready-to-use package with:

```text
WiiFormatExchanger-v1.0.0-win64/
├── WiiConverter.exe
├── convert.bat
├── config.ini
└── README.md
```

> `config.ini` inside the release is still a sample configuration file and must be edited before first use.

---

## Requirements

> Using `iso_to_wbfs.bat`? You can skip this section: it installs Python and downloads `wit.exe` (and `nkit.exe` when needed) on its own.

### Python version

If you want to run the script directly, you need **Python 3.8 or newer**.

1. Download Python from <https://www.python.org/downloads/>.
2. During installation, make sure **"Add Python to PATH"** is enabled.
3. Verify the installation in Command Prompt:

```cmd
python --version
```

The script uses only Python's standard library, so no extra Python packages are required.

> On a stock Windows 10/11 PC, typing `python` without Python installed opens the Microsoft Store. The `.bat` launchers detect that stub and ignore it.

### DolphinTool.exe

Only needed for **RVZ** conversions. **DolphinTool.exe** is included with **Dolphin Emulator**.

1. Download Dolphin from <https://dolphin-emu.org/download/>.
2. Install or extract it to a folder such as `C:\Dolphin\`.
3. Locate `DolphinTool.exe` and copy its full path.

### wit.exe

**wit.exe** is part of **Wiimms ISO Tools** and is required for all workflows involving **WBFS**.

You normally do not have to install it: when it cannot be found, the converter downloads the official
`wit-v3.05a-r8638-cygwin64.zip` from <https://wit.wiimm.de/>, verifies its SHA-256 checksum, and unpacks
`wit.exe` (with the DLLs it needs) into `tools\wit\` next to the script. Pass `--no-download` to disable this.

To install it manually instead:

1. Download Wiimms ISO Tools from <https://wit.wiimm.de/download.html>.
2. Extract it to a folder such as `C:\WiimmsISOTools\`.
3. Either put its `bin` folder contents into `tools\wit\`, or set `wit_tool` in `config.ini` to the full path of `wit.exe`.

### NKit images (`*.nkit.iso`)

Files named `Something.nkit.iso` (or carrying the `NKIT` marker at offset 0x200) were shrunk with
[NKit](https://github.com/Nanook/NKit). They play in Dolphin, but they are not real disc images:
WIT stops with `No valid source file found`, and a Wii USB loader cannot use them either.

The converter recognises them and uses **NKit 2** (`nkit.exe`, a self-contained command line tool,
no .NET runtime needed). When it is not installed, `NKit_CLI_win-x64_2.1.0.zip` is downloaded from the
official GitHub releases, SHA-256 verified, and unpacked into `tools\nkit\`.

Two ways are supported, selected with `[batch] nkit_mode` in `config.ini`:

| `nkit_mode` | What happens | Notes |
|---|---|---|
| `wbfs` (default) | `nkit -task convert -convert wbfs` writes the WBFS directly | Fastest, no temporary file |
| `iso` | `nkit -task expand` restores the full ISO, then `wit` makes the WBFS | Needs ~4.4 GB of temporary space per game |

If the direct way fails for a game, the ISO way is tried automatically for that game. Restoring an
NKit image takes noticeably longer than converting a plain ISO, because the removed data has to be
regenerated and the partition hashes recalculated.

> Some antivirus products flag the unsigned `nkit.exe` as suspicious. It is a clean automated build
> (see the NKit wiki); allow it if your antivirus quarantines it.

---

## Configuration

The configuration is optional. If `config.ini` is missing it is created automatically with the defaults below
(tools auto-detected, `D:\Wii\ISO` → `D:\Wii\wbfs`).

In the repository, the sample configuration file is named **`config.sample.ini`**.
In the precompiled release package, the file is named **`config.ini`**.

Example configuration:

```ini
[paths]
dolphin_tool =
wit_tool =
nkit_tool =

[output]
output_rvz = .\RVZ
output_wbfs = D:\Wii\wbfs

[conversion]
rvz_compression = zstd
rvz_compression_level = 5

[batch]
input_iso = D:\Wii\ISO
output_wbfs = D:\Wii\wbfs
name_format = {name} [{id}]
nkit_mode = wbfs
```

### Configuration keys

| Key | Description | Default |
|---|---|---|
| `dolphin_tool` | Full path to `DolphinTool.exe`; empty = auto-detect | *(empty)* |
| `wit_tool` | Full path to `wit.exe`; empty = auto-detect, then auto-download | *(empty)* |
| `nkit_tool` | Full path to `nkit.exe` (NKit 2, only for `*.nkit.iso`); empty = auto-detect, then auto-download | *(empty)* |
| `output_rvz` | Output folder for RVZ files | `.\RVZ` |
| `output_wbfs` | Output folder for WBFS files | `D:\Wii\wbfs` |
| `rvz_compression` | RVZ compression codec: `none`, `zstd`, `bzip2`, `lzma`, `lzma2` | `zstd` |
| `rvz_compression_level` | Compression level (`1-22` for `zstd`, `1-9` for others) | `5` |
| `[batch] input_iso` | Folder scanned for `.iso` files in batch mode | `D:\Wii\ISO` |
| `[batch] output_wbfs` | Folder where batch mode writes `.wbfs` files | `D:\Wii\wbfs` |
| `[batch] name_format` | Output name for ISO → WBFS. `{name}` = ISO file name (a trailing `.nkit` is dropped), `{id}` = game ID, `{title}` = disc title. Kept as-is if the ISO name already contains the game ID | `{name} [{id}]` |
| `[batch] nkit_mode` | How NKit images are converted: `wbfs` (NKit writes WBFS directly) or `iso` (NKit restores a full ISO, then wit) | `wbfs` |

Tools are searched in this order: the configured path, next to the script, `tools\wit\` / `tools\dolphin\`,
the system `PATH`, and the usual install folders (`C:\WiimmsISOTools\`, `C:\Program Files\Wiimm\WIT\`,
`C:\Dolphin\`, `C:\Program Files\Dolphin\`). If `wit.exe` is still not found it is downloaded.

### Example: absolute output folders

```ini
output_rvz = D:\WiiGames\RVZ
output_wbfs = D:\WiiGames\WBFS
```

### Example: output folders relative to the script or .exe

```ini
output_rvz = .\RVZ
output_wbfs = .\WBFS
```

---

## Usage

### Batch: convert every ISO in `D:\Wii\ISO` to WBFS in `D:\Wii\wbfs`

Double-click **`iso_to_wbfs.bat`** (see *Quick start* above). Every `.iso` in `D:\Wii\ISO`, including
sub-folders, is written as `Name [GAMEID].wbfs` into `D:\Wii\wbfs`.

What happens on each run:

```text
1. Find a working Python (or install it with winget)
2. Find wit.exe (or download it into tools\wit\); if NKit images are present, also nkit.exe (tools\nkit\)
3. Delete unfinished files left in D:\Wii\wbfs\.incomplete\ by an interrupted run
4. Read the game ID of every .wbfs already in D:\Wii\wbfs (any name, any sub-folder)
5. For each ISO: skip if that game is already there, otherwise convert into .incomplete\
   (NKit images are restored with NKit first) and move the finished file into D:\Wii\wbfs
6. Print a converted / skipped / failed summary
```

Equivalent command line:

```cmd
python convert.py --batch "D:\Wii\ISO" --to wbfs --output "D:\Wii\wbfs"
```

Useful flags:

| Flag | Effect |
|---|---|
| `--batch [FOLDER]` | Batch mode. Without a folder, uses `[batch] input_iso` from `config.ini` |
| `--to rvz\|wbfs` | Target format for ISO input; skips the Yes/No dialog |
| `--output FOLDER` | Output folder, overrides `config.ini` |
| `--overwrite` | Re-convert games that already exist in the output folder |
| `--no-download` | Never download `wit.exe` / `nkit.exe` automatically |
| `--no-pause` | Do not wait for ENTER at the end (for scripts/schedulers) |

### Method 1 — Drag & drop with `convert.bat`

1. Optionally edit `config.ini` (it is created automatically on first run).
2. Drag a `.rvz`, `.wbfs`, or `.iso` file onto `convert.bat`.
3. A console window opens and shows the conversion progress.
4. The converted file is saved in the output folder defined in the configuration.

### Method 2 — Drag & drop with `WiiConverter.exe`

If you downloaded the precompiled release:

1. Optionally edit `config.ini`.
2. Drag a `.rvz`, `.wbfs`, or `.iso` file onto `WiiConverter.exe`.
3. Wait for the conversion to complete.

### Method 3 — Command Prompt

```cmd
python convert.py "C:\Games\SuperMarioGalaxy.rvz"
python convert.py "C:\Games\Zelda.wbfs"
python convert.py "C:\Games\MetroidPrime3.iso"
python convert.py "C:\Games\MetroidPrime3.iso" --to wbfs
```

---

## ISO target selection

When the input file is an **ISO**, the program opens a native Windows **Yes/No** dialog:

- **Yes** → convert to **RVZ**
- **No** → convert to **WBFS**

Pass `--to rvz` or `--to wbfs` on the command line to skip the dialog.
Only the tool the chosen flow needs is required: ISO → WBFS works with just `wit.exe`.

The original ISO file is never deleted.

---

## Supported workflows

```text
WBFS -> RVZ : WIT (WBFS -> temporary ISO) + DolphinTool (ISO -> RVZ)
RVZ -> WBFS : DolphinTool (RVZ -> temporary ISO) + WIT (ISO -> WBFS)
ISO  -> RVZ : direct DolphinTool conversion
ISO  -> WBFS: direct WIT conversion
```

### WBFS → RVZ

The file is first converted to a temporary ISO, then compressed to RVZ using the selected codec.
After the conversion is completed, the temporary ISO is removed automatically.

### RVZ → WBFS

The file is first expanded into a temporary ISO and then converted to WBFS.
This is useful for Wii loaders or setups that do not support RVZ directly.

### ISO → RVZ / WBFS

When the source file is an ISO, the user chooses the target format through the native Windows dialog.
The original ISO is preserved.

---

## What happens during conversion

```text
Step 0  Check that the source file exists and has a supported extension
Step 1  Read config.ini and locate DolphinTool.exe / wit.exe
Step 2  Create the output folder if it does not exist
Step 3  Run the correct conversion command(s)
Step 4  Show source size, output size, and savings percentage when relevant
Step *  Remove temporary files/folders when needed
```

---

## Troubleshooting

| Message | Cause | Solution |
|---|---|---|
| `DolphinTool not found` | Dolphin is not installed or `dolphin_tool` is wrong | Install Dolphin or fix `dolphin_tool` |
| `Automatic download of wit.exe failed` | No internet, or wit.wiimm.de unreachable | Download the cygwin64 zip from <https://wit.wiimm.de/download.html> and copy its `bin` folder contents into `tools\wit\` |
| `wit: No valid source file found` | The file is an NKit image (`*.nkit.iso`) or not a disc image at all | NKit images are handled automatically (see *NKit images*); otherwise check the file |
| `Automatic download of nkit.exe failed` | No internet, or github.com unreachable | Download `NKit_CLI_win-x64_2.1.0.zip` from <https://github.com/Nanook/NKit/releases> and unzip it into `tools\nkit\` |
| Colours show as `←[92m` | Old console without VT support | Cosmetic only; use Windows Terminal or ignore |
| `Python could not be installed automatically` | `winget` missing or blocked | Install Python from python.org with "Add python.exe to PATH" ticked, then run the `.bat` again |
| `Not enough free space` | Output drive is nearly full | Free up space; a WBFS is at most as large as its ISO |
| `Already converted as ... (same game ID)` | That game already exists in the output folder under another name | Nothing to do; use `--overwrite` to redo it |
| `Unsupported format` | File is not `.rvz`, `.wbfs`, or `.iso` | Use a supported format |
| `... failed (exit code 1)` | DolphinTool or WIT returned an error | Check that the source file is valid and not corrupted |
| Window closes immediately | Python not found in PATH | Reinstall Python and enable **Add Python to PATH** |

---

## System requirements

- Windows 10 / 11 (64-bit)
- Python 3.8+ for the script version (installed automatically by `iso_to_wbfs.bat` when missing)
- Dolphin Emulator (`DolphinTool.exe`), only for RVZ conversions
- Wiimms ISO Tools (`wit.exe`), downloaded automatically when missing
- NKit 2 (`nkit.exe`), downloaded automatically when NKit images are present
- Enough free disk space for temporary ISO creation when required

---

## Technical notes

- `convert.py` is a wrapper around **DolphinTool** and **WIT**.
- The script uses only Python's standard library.
- Temporary files are created only when needed for WBFS-related conversion flows.
- The original source file is never modified or deleted.
- Output folders are separated by format: one for RVZ and one for WBFS.
- ISO → WBFS writes into `<output>\.incomplete\` and moves the file into place only after `wit` succeeds.
- Game IDs are read from the disc header (offset 0 of an ISO, second sector of a WBFS file).
- `wit.exe` is downloaded from <https://wit.wiimm.de/> and `nkit.exe` from <https://github.com/Nanook/NKit/releases> only; both archives' SHA-256 are pinned in `convert.py`.
- NKit images are detected by the `NKIT` magic at offset 0x200 (the same check Dolphin uses) or a `.nkit.` in the file name.

---

## License

This project is released under the **MIT License**.
