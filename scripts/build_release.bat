@echo off
REM Kaelovun — one-command release build.
REM Builds from Kaelovun.spec, verifies the runnable, and zips dist\Kaelovun.
REM Usage: scripts\build_release.bat [version]
REM   version defaults to 1.3.1 -> Kaelovun-v1.3.1.zip
setlocal
cd /d "%~dp0.."

set VERSION=%1
if "%VERSION%"=="" set VERSION=1.3.1
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

if exist "%OUT%" del /f /q "%OUT%"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\Kaelovun' -DestinationPath '%OUT%' -Force"
if errorlevel 1 (
  echo ZIP FAILED.
  exit /b 1
)

echo Done: %OUT%
echo Extract the whole zip and run Kaelovun\Kaelovun.exe - never move the exe alone.
