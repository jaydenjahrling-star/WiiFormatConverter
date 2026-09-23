@echo off
setlocal EnableExtensions
rem -------------------------------------------------------------
rem  Wii Converter - drag & drop launcher
rem  Drop a .rvz, .wbfs or .iso file onto this file.
rem  For a whole folder of ISOs use iso_to_wbfs.bat instead.
rem -------------------------------------------------------------
if "%~1"=="" (
    echo Drag and drop a .rvz, .wbfs or .iso file onto this file.
    pause
    exit /b 1
)
set "PY="
set "PYARGS="
for %%I in (py.exe) do if not "%%~$PATH:I"=="" (
    "%%~$PATH:I" -3 -c "import sys" >nul 2>&1 && (
        set "PY=%%~$PATH:I"
        set "PYARGS=-3"
    )
)
if not defined PY for %%I in (python.exe) do if not "%%~$PATH:I"=="" (
    "%%~$PATH:I" -c "import sys" >nul 2>&1 && set "PY=%%~$PATH:I"
)
if not defined PY (
    echo [ERR] Python is not installed. Run iso_to_wbfs.bat once - it installs Python -
    echo       or install it from https://www.python.org/downloads/windows/
    pause
    exit /b 1
)
"%PY%" %PYARGS% "%~dp0convert.py" %*
exit /b %errorlevel%
