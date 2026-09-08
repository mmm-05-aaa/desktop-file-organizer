@echo off
setlocal DisableDelayedExpansion
set "PYTHONPATH="
set "PYTHONHOME="
if defined DESKTOP_ORGANIZER_PYTHON goto explicit
where py >nul 2>&1
if errorlevel 1 goto python
py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 goto python
py -3 "%~dp0reset_demo.py" --root "%~dp0demo-data"
exit /b %errorlevel%
:python
where python >nul 2>&1
if errorlevel 1 goto missing
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 goto missing
python "%~dp0reset_demo.py" --root "%~dp0demo-data"
exit /b %errorlevel%
:explicit
"%DESKTOP_ORGANIZER_PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 goto missing
"%DESKTOP_ORGANIZER_PYTHON%" "%~dp0reset_demo.py" --root "%~dp0demo-data"
exit /b %errorlevel%
:missing
echo Python 3.10+ is required. Set DESKTOP_ORGANIZER_PYTHON to a Python executable path.
exit /b 1
