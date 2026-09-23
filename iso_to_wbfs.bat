@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Wii Converter - ISO to WBFS
cd /d "%~dp0"

rem =============================================================
rem  Wii Converter - one-click batch ISO -> WBFS
rem
rem  Converts every .iso in ISO_DIR into a .wbfs in WBFS_DIR.
rem  - Installs Python (via winget) if it is missing.
rem  - convert.py downloads wit.exe (Wiimms ISO Tools) if it is missing.
rem  - Games already present in WBFS_DIR are skipped, so you can re-run
rem    this any time after adding new ISOs. Original ISOs are never deleted.
rem =============================================================

set "ISO_DIR=D:\Wii\ISO"
set "WBFS_DIR=D:\Wii\wbfs"

echo.
echo  Wii Converter - batch ISO to WBFS
echo  Source : %ISO_DIR%
echo  Target : %WBFS_DIR%
echo.

call :find_python
if defined PY goto :run

echo [INFO] Python is not installed. Installing it with winget (Windows Package Manager)...
where winget >nul 2>&1
if errorlevel 1 (
    echo [WARN] winget is not available on this PC.
    goto :manual_python
)
winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
call :find_python
if defined PY goto :run
winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
call :find_python
if defined PY goto :run

:manual_python
echo.
echo [ERR] Python could not be installed automatically.
echo       1. Install Python from https://www.python.org/downloads/windows/
echo          and tick "Add python.exe to PATH" in the installer.
echo       2. Double-click this file again.
start "" "https://www.python.org/downloads/windows/"
echo.
pause
exit /b 1

:run
echo [OK] Python : %PY% %PYARGS%
echo.
"%PY%" %PYARGS% "%~dp0convert.py" --batch "%ISO_DIR%" --to wbfs --output "%WBFS_DIR%"
rem convert.py pauses itself on exit codes 0/1; anything else means Python itself failed to start
if not "%errorlevel%"=="0" if not "%errorlevel%"=="1" pause
exit /b %errorlevel%

rem -------------------------------------------------------------
rem  find_python: sets PY (full path) and PYARGS. Every candidate is
rem  test-run, because on a stock Windows 10/11 "python" on PATH is a
rem  Microsoft Store stub that only prints an advert and exits.
rem -------------------------------------------------------------
:find_python
set "PY="
set "PYARGS="

rem 1) py launcher (comes with python.org installs, never the Store stub)
for %%I in (py.exe) do if not "%%~$PATH:I"=="" (
    "%%~$PATH:I" -3 -c "import sys" >nul 2>&1 && (
        set "PY=%%~$PATH:I"
        set "PYARGS=-3"
    )
)
if defined PY goto :eof

rem 2) python.exe / python3.exe on PATH, only if it really runs
for %%N in (python.exe python3.exe) do (
    for %%I in (%%N) do if not defined PY if not "%%~$PATH:I"=="" (
        "%%~$PATH:I" -c "import sys" >nul 2>&1 && set "PY=%%~$PATH:I"
    )
)
if defined PY goto :eof

rem 3) standard install folders (also finds a fresh winget install that is
rem    not on this window's PATH yet)
for /d %%D in ("%LocalAppData%\Programs\Python\Python3*" "%ProgramFiles%\Python3*" "C:\Python3*") do (
    if not defined PY if exist "%%~D\python.exe" (
        "%%~D\python.exe" -c "import sys" >nul 2>&1 && set "PY=%%~D\python.exe"
    )
)
goto :eof
