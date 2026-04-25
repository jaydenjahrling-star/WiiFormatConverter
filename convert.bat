@echo off
:: ─────────────────────────────────────────────────────────────
:: Wii Converter - Drag & Drop Launcher
:: Trascina un file .rvz o .wbfs su questo file .bat
:: ─────────────────────────────────────────────────────────────
python "%~dp0convert.py" %1
