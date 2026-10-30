@echo off
REM Kaelovun one-command release build.
REM Builds from Kaelovun.spec, verifies the runnable, zips dist\Kaelovun and
REM builds the NSIS installer.
REM Usage: scripts\build_release.bat [version]
REM   version defaults to VERSION in cli.py -> Kaelovun-v1.7.0.zip
setlocal
cd /d "%~dp0.."

set VERSION=%1
if "%VERSION%"=="" (
  for /f "tokens=3 delims= " %%v in ('findstr /b /c:"VERSION = " cli.py') do set VERSION=%%~v
)
if "%VERSION%"=="" (
  echo ERROR: could not read VERSION from cli.py.
  exit /b 1
)
set OUT=Kaelovun-v%VERSION%.zip

echo Building Kaelovun v%VERSION% from Kaelovun.spec...
REM Prefer the project venv (has pywin32/Pillow); fall back to system python.
if exist ".venv\Scripts\python.exe" (
  .venv\Scripts\python.exe -m PyInstaller Kaelovun.spec --noconfirm
) else (
  python -m PyInstaller Kaelovun.spec --noconfirm
)
if errorlevel 1 (
  echo BUILD FAILED.
  exit /b 1
)

if not exist "dist\Kaelovun\Kaelovun.exe" (
  echo ERROR: dist\Kaelovun\Kaelovun.exe not found. Did the spec change?
  exit /b 1
)
dir /b "dist\Kaelovun\_internal\python3*.dll" >nul 2>&1
if errorlevel 1 (
  echo ERROR: dist\Kaelovun\_internal\python3*.dll missing. Build incomplete.
  exit /b 1
)

echo Verified: dist\Kaelovun\Kaelovun.exe + _internal\python DLL present.
echo NOTE: never run build\Kaelovun\Kaelovun.exe - it always fails with
echo "Failed to load Python DLL". The runnable is dist\Kaelovun\Kaelovun.exe.

REM Local settings, logs and session state must not go into a release.
if exist "dist\Kaelovun\_internal\data" rmdir /s /q "dist\Kaelovun\_internal\data"

if exist "%OUT%" del /f /q "%OUT%"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\Kaelovun' -DestinationPath '%OUT%' -Force"
if errorlevel 1 (
  echo ZIP FAILED.
  exit /b 1
)
echo Done: %OUT%

powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\build_installer.ps1" -Version %VERSION%
if errorlevel 1 (
  echo INSTALLER FAILED.
  exit /b 1
)

echo Extract the whole zip and run Kaelovun\Kaelovun.exe - never move the exe alone.
echo Or hand out dist\Kaelovun-Setup-%VERSION%.exe, which installs per user.
