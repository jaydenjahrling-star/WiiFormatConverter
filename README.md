# Wii Converter — RVZ ↔ WBFS ↔ ISO

A simple Windows tool to convert Wii disc image files between **RVZ**, **WBFS**, and **ISO** formats using **DolphinTool** and **WIT**.

It supports **drag & drop** and works with both the Python script and the precompiled Windows release.

---

## Features

- Convert **WBFS → RVZ**
- Convert **RVZ → WBFS**
- Convert **ISO → RVZ**
- Convert **ISO → WBFS**
- **Batch mode**: convert a whole folder of ISOs to WBFS in one go (`iso_to_wbfs.bat`)
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
├── iso_to_wbfs.bat         ← batch launcher: D:\Wii\ISO → D:\Wii\wbfs
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

### Python version

If you want to run the script directly, you need **Python 3.8 or newer**.

1. Download Python from <https://www.python.org/downloads/>.
2. During installation, make sure **"Add Python to PATH"** is enabled.
3. Verify the installation in Command Prompt:

```cmd
python --version
```

The script uses only Python's standard library, so no extra Python packages are required.

### DolphinTool.exe

**DolphinTool.exe** is included with **Dolphin Emulator**.

1. Download Dolphin from <https://dolphin-emu.org/download/>.
2. Install or extract it to a folder such as `C:\Dolphin\`.
3. Locate `DolphinTool.exe` and copy its full path.

### wit.exe

**wit.exe** is part of **Wiimms ISO Tools**.

It is required for all workflows involving **WBFS**.

1. Download Wiimms ISO Tools from <https://wit.wiimm.de/>.
2. Extract it to a folder such as `C:\WiimmsISOTools\`.
3. Locate `wit.exe` and copy its full path.

---

## Configuration

In the repository, the sample configuration file is named **`config.sample.ini`**.

In the precompiled release package, the file is named **`config.ini`**, but it is still a sample and must be edited before use.

Example configuration:

```ini
[paths]
dolphin_tool = C:\Dolphin\DolphinTool.exe
wit_tool = C:\WiimmsISOTools\wit.exe

[output]
output_rvz = .\RVZ
output_wbfs = .\WBFS

[conversion]
rvz_compression = zstd
rvz_compression_level = 5

[batch]
input_iso = D:\Wii\ISO
output_wbfs = D:\Wii\wbfs
```

### Configuration keys

| Key | Description | Default |
|---|---|---|
| `dolphin_tool` | Full path to `DolphinTool.exe` | `C:\Dolphin\DolphinTool.exe` |
| `wit_tool` | Full path to `wit.exe` | `C:\WiimmsISOTools\wit.exe` |
| `output_rvz` | Output folder for RVZ files | `.\RVZ` |
| `output_wbfs` | Output folder for WBFS files | `.\WBFS` |
| `rvz_compression` | RVZ compression codec: `none`, `zstd`, `bzip2`, `lzma`, `lzma2` | `zstd` |
| `rvz_compression_level` | Compression level (`1-22` for `zstd`, `1-9` for others) | `5` |
| `[batch] input_iso` | Folder scanned for `.iso` files in batch mode | `D:\Wii\ISO` |
| `[batch] output_wbfs` | Folder where batch mode writes `.wbfs` files | `D:\Wii\wbfs` |

`wit.exe` and `DolphinTool.exe` are also auto-detected next to the script, on the system `PATH`,
and in the usual install folders (`C:\WiimmsISOTools\`, `C:\Program Files\Wiimm\WIT\`,
`C:\Dolphin\`, `C:\Program Files\Dolphin\`) if the configured path does not exist.

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

1. Install [Wiimms ISO Tools](https://wit.wiimm.de/) (only `wit.exe` is needed for this).
2. Copy `config.sample.ini` to `config.ini` (the tool creates one on first run if it is missing).
3. Double-click **`iso_to_wbfs.bat`**.

Every `.iso` in `D:\Wii\ISO` is written as `<same name>.wbfs` into `D:\Wii\wbfs`.
Files that already exist in the output folder are skipped, so you can re-run it after adding
new ISOs. Original ISOs are never deleted. A summary of converted / skipped / failed files is
printed at the end.

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
| `--overwrite` | Re-convert files that already exist in the output folder |
| `--no-pause` | Do not wait for ENTER at the end (for scripts/schedulers) |

### Method 1 — Drag & drop with `convert.bat`

1. Edit `config.ini` (or create it from `config.sample.ini` if you are using the repository version).
2. Drag a `.rvz`, `.wbfs`, or `.iso` file onto `convert.bat`.
3. A console window opens and shows the conversion progress.
4. The converted file is saved in the output folder defined in the configuration.

### Method 2 — Drag & drop with `WiiConverter.exe`

If you downloaded the precompiled release:

1. Edit `config.ini`.
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
| `DolphinTool.exe not found` | Wrong path in the configuration file | Check and fix `dolphin_tool` |
| `wit.exe not found` | Wrong path in the configuration file | Check and fix `wit_tool` |
| `Unsupported format` | File is not `.rvz`, `.wbfs`, or `.iso` | Use a supported format |
| `... failed (exit code 1)` | DolphinTool or WIT returned an error | Check that the source file is valid and not corrupted |
| `config.ini not found` | Missing config file | Create it from `config.sample.ini` or edit the included sample file |
| Window closes immediately | Python not found in PATH | Reinstall Python and enable **Add Python to PATH** |

---

## System requirements

- Windows 10 / 11 (64-bit)
- Python 3.8+ for the script version
- Dolphin Emulator (`DolphinTool.exe`)
- Wiimms ISO Tools (`wit.exe`)
- Enough free disk space for temporary ISO creation when required

---

## Technical notes

- `convert.py` is a wrapper around **DolphinTool** and **WIT**.
- The script uses only Python's standard library.
- Temporary files are created only when needed for WBFS-related conversion flows.
- The original source file is never modified or deleted.
- Output folders are separated by format: one for RVZ and one for WBFS.

---

## License

This project is released under the **MIT License**.
