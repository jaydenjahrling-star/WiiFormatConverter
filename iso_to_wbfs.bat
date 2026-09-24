@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Wii Converter - ISO to WBFS
cd /d "%~dp0"

rem =============================================================
rem  Wii Converter - one-click batch ISO -> WBFS
rem
rem  Converts every .iso in the input folder into a .wbfs in the
rem  output folder. The folders are set in config.ini, section
rem  [batch] (input_iso / output_wbfs). Defaults: D:\Wii\ISO -> D:\Wii\wbfs
rem  - Installs Python 3 with winget if it is missing.
rem  - convert.py downloads wit.exe and nkit.exe if they are missing.
rem  - Games already present in the output folder are skipped, so you
rem    can re-run this after adding ISOs. Original ISOs are never deleted.
rem =============================================================

if not exist "%~dp0convert.py" (
    echo [ERR] convert.py was not found next to this file.
    echo       If you opened the ZIP without extracting it, extract the whole
    echo       folder first, then run iso_to_wbfs.bat from the extracted folder.
    echo.
    pause
    exit /b 1
)

echo.
echo  Wii Converter - batch ISO to WBFS
echo  Folders: see config.ini, section [batch] - default D:\Wii\ISO to D:\Wii\wbfs
echo.

call :find_python
if defined PY goto :run

echo [INFO] Python 3.8 or newer was not found. Installing Python with winget ...
where winget >nul 2>&1
if errorlevel 1 (
    echo [WARN] winget is not available on this PC.
    goto :manual_python
)
winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
call :find_python
if defined PY goto :run
winget install -e --id Python.Python.3.12 --silent --force --accept-package-agreements --accept-source-agreements
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
echo [OK] Python : "%PY%" %PYARGS%
echo.
"%PY%" %PYARGS% "%~dp0convert.py" --batch --to wbfs --no-pause
set "RC=%errorlevel%"
echo.
if not "%RC%"=="0" echo [ERR] The converter ended with exit code %RC% - see the messages above.
pause
exit /b %RC%

rem -------------------------------------------------------------
rem  find_python: sets PY (full path) and PYARGS. Every candidate is
rem  test-run and must be Python 3.8+, because on a stock Windows 10/11
rem  "python" on PATH is a Microsoft Store stub that only prints an
rem  advert, and an old Python 2/3.x may be installed by other software.
rem -------------------------------------------------------------
:find_python
set "PY="
set "PYARGS="

rem 1) py launcher (comes with python.org installs, never the Store stub)
for %%I in (py.exe) do if not "%%~$PATH:I"=="" (
    "%%~$PATH:I" -3 -c "import sys; assert sys.hexversion >= 0x03080000" >nul 2>&1 && (
        set "PY=%%~$PATH:I"
        set "PYARGS=-3"
    )
)
if defined PY goto :eof

rem 2) python.exe / python3.exe on PATH, only if it really runs and is 3.8+
for %%N in (python.exe python3.exe) do (
    for %%I in (%%N) do if not defined PY if not "%%~$PATH:I"=="" (
        "%%~$PATH:I" -c "import sys; assert sys.hexversion >= 0x03080000" >nul 2>&1 && set "PY=%%~$PATH:I"
    )
)
if defined PY goto :eof

rem 3) standard install folders (also finds a fresh winget install that is
rem    not on this window's PATH yet)
for /d %%D in ("%LocalAppData%\Programs\Python\Python3*" "%ProgramFiles%\Python3*" "C:\Python3*") do (
    if not defined PY if exist "%%~D\python.exe" (
        "%%~D\python.exe" -c "import sys; assert sys.hexversion >= 0x03080000" >nul 2>&1 && set "PY=%%~D\python.exe"
    )
)
goto :eof
