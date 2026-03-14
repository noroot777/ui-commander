@echo off
setlocal ENABLEEXTENSIONS

set "SCRIPT_DIR=%~dp0"
set "STATE_ROOT=%USERPROFILE%\.ui-commander"
set "LOG_FILE=%STATE_ROOT%\native-host.log"
set "PYTHON_HINT_FILE=%STATE_ROOT%\python-bin"

if not exist "%STATE_ROOT%" mkdir "%STATE_ROOT%"

set "PYTHON_BIN="
set "PYTHON_HINT="
if exist "%PYTHON_HINT_FILE%" set /p PYTHON_HINT=<"%PYTHON_HINT_FILE%"

if /I not "%PYTHON_HINT%"=="" (
  echo %PYTHON_HINT% | find /I "Microsoft\WindowsApps\python" >nul
  if errorlevel 1 (
    if exist "%PYTHON_HINT%" set "PYTHON_BIN=%PYTHON_HINT%"
  )
)

if defined UI_COMMANDER_PYTHON if exist "%UI_COMMANDER_PYTHON%" set "PYTHON_BIN=%UI_COMMANDER_PYTHON%"

if not defined PYTHON_BIN (
  for /f "usebackq delims=" %%I in (`py -3 -c "import sys; print(sys.executable)" 2^>nul`) do (
    if not defined PYTHON_BIN set "PYTHON_BIN=%%I"
  )
)

if not defined PYTHON_BIN (
  for %%P in (python.exe python3.exe) do (
    if not defined PYTHON_BIN (
      for /f "delims=" %%I in ('where %%P 2^>nul') do (
        echo %%I | find /I "Microsoft\WindowsApps\python" >nul
        if errorlevel 1 if not defined PYTHON_BIN set "PYTHON_BIN=%%I"
      )
    )
  )
)

if not defined PYTHON_BIN (
  >>"%LOG_FILE%" echo [%date% %time%] native_host_entry missing_python hint_file=%PYTHON_HINT_FILE%
  exit /b 1
)

>>"%LOG_FILE%" echo [%date% %time%] native_host_entry start
>>"%LOG_FILE%" echo [%date% %time%] cwd=%CD%
>>"%LOG_FILE%" echo [%date% %time%] python=%PYTHON_BIN%

"%PYTHON_BIN%" "%SCRIPT_DIR%companion.py" native-host 2>>"%LOG_FILE%"
