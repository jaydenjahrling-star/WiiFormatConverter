@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Wii Converter
cd /d "%~dp0"
rem -------------------------------------------------------------
rem  Wii Converter - drag & drop launcher
rem  Drop one or more .rvz, .wbfs or .iso files onto this file.
rem  For a whole folder of ISOs use iso_to_wbfs.bat instead.
rem  Command-line options: use  python convert.py --help
rem -------------------------------------------------------------
if not exist "%~dp0convert.py" (
    echo [ERR] convert.py was not found next to this file.
    echo       If you opened the ZIP without extracting it, extract the whole folder first.
    pause
    exit /b 1
)
if "%~1"=="" (
    echo Drag and drop a .rvz, .wbfs or .iso file onto this file.
    pause
    exit /b 1
)

call :find_python
if not defined PY (
    echo [ERR] Python 3.8 or newer was not found.
    echo       Run iso_to_wbfs.bat once - it installs Python - or install it from
    echo       https://www.python.org/downloads/windows/ with "Add python.exe to PATH" ticked.
    pause
    exit /b 1
)

set "RC=0"
:next
if "%~1"=="" goto :done
"%PY%" %PYARGS% "%~dp0convert.py" "%~1" --no-pause
if not "%errorlevel%"=="0" set "RC=%errorlevel%"
shift
goto :next

:done
echo.
if not "%RC%"=="0" echo [ERR] The converter ended with exit code %RC% - see the messages above.
pause
exit /b %RC%

:find_python
set "PY="
set "PYARGS="
for %%I in (py.exe) do if not "%%~$PATH:I"=="" (
    "%%~$PATH:I" -3 -c "import sys; assert sys.hexversion >= 0x03080000" >nul 2>&1 && (
        set "PY=%%~$PATH:I"
        set "PYARGS=-3"
    )
)
if defined PY goto :eof
for %%N in (python.exe python3.exe) do (
    for %%I in (%%N) do if not defined PY if not "%%~$PATH:I"=="" (
        "%%~$PATH:I" -c "import sys; assert sys.hexversion >= 0x03080000" >nul 2>&1 && set "PY=%%~$PATH:I"
    )
)
if defined PY goto :eof
for /d %%D in ("%LocalAppData%\Programs\Python\Python3*" "%ProgramFiles%\Python3*" "C:\Python3*") do (
    if not defined PY if exist "%%~D\python.exe" (
        "%%~D\python.exe" -c "import sys; assert sys.hexversion >= 0x03080000" >nul 2>&1 && set "PY=%%~D\python.exe"
    )
)
goto :eof
