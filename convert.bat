"%PY%" %PYARGS% "%~dp0convert.py" %*
rem convert.py pauses itself on 0/1; anything else means Python itself failed to start
if not "%errorlevel%"=="0" if not "%errorlevel%"=="1" pause
exit /b %errorlevel%