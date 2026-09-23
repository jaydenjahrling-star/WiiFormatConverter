@echo off
:: ─────────────────────────────────────────────────────────────
:: Wii Converter - Batch ISO -> WBFS
:: Converts every .iso in D:\Wii\ISO into a .wbfs in D:\Wii\wbfs
:: Double-click this file. Original ISOs are never deleted.
:: Files that already exist in D:\Wii\wbfs are skipped.
:: ─────────────────────────────────────────────────────────────
python "%~dp0convert.py" --batch "D:\Wii\ISO" --to wbfs --output "D:\Wii\wbfs"
