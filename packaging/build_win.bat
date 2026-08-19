
@echo off
REM Run from the project root regardless of where this script is invoked from.
cd /d "%~dp0\.."

REM ===============================================
REM  Setup the correct python environment
REM ===============================================
echo "Activating win virtual environment for Python"
call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo Activating virtual environment failed
    exit /b 1
)

REM ===============================================
REM Running build for architecture
REM ===============================================
for /f %%a in ('wmic os get osarchitecture ^| findstr /r "[0-9]"') do set ARCH=%%a
echo Running build for %ARCH% architecture

REM ===============================================
REM Clean-up
REM ===============================================
rmdir /s /q dist
rmdir /s /q build

REM ===============================================
REM Generate version_build from git commit count
REM ===============================================
for /f %%b in ('git rev-list --count HEAD') do set VERSION_BUILD=%%b
if errorlevel 1 (
    echo Generating version_build failed
    exit /b 1
)
echo %VERSION_BUILD%> src\guitar_tap\version_build
echo gen_version_build: version_build = %VERSION_BUILD%

REM ===============================================
REM Run pyinstaller
REM ===============================================
REM Get the full version (e.g. 1.0.245) matching what the spec file produces
set /p version=<src\guitar_tap\version
set /p version_build=<src\guitar_tap\version_build

REM ===============================================
REM Fail early if the version number is stale — already-tagged release + newer code.
REM Mirrors packaging/check_version_freshness.sh. Uses the BASE version (before the
REM build number is appended below) as the tag name.
REM ===============================================
setlocal enabledelayedexpansion
git rev-parse -q --verify refs/tags/%version% >nul 2>&1
if not errorlevel 1 (
    set AHEAD=0
    for /f %%a in ('git rev-list --count %version%..HEAD') do set AHEAD=%%a
    if not "!AHEAD!"=="0" (
        echo ======================================================================
        echo BUILD BLOCKED - stale version number.
        echo   src\guitar_tap\version says %version%, which is already released
        echo   ^(git tag '%version%' exists^), but HEAD is !AHEAD! commit^(s^) newer.
        echo   Bump src\guitar_tap\version to the next release number before building.
        echo ======================================================================
        endlocal
        exit /b 1
    )
)
endlocal

REM ===============================================
REM Fail if docs\ReleaseNotes.md was not rolled over after the last release.
REM Required on every platform even though Windows does not generate the notes.
REM Mirrors packaging\check_release_notes.sh: the newest tag must appear as a
REM frozen "## Version <tag> " header. (findstr /b /c: = literal, line-start.)
REM ===============================================
set LATEST_TAG=
for /f %%t in ('git describe --tags --abbrev^=0 2^>nul') do set LATEST_TAG=%%t
if not "%LATEST_TAG%"=="" (
    findstr /b /c:"## Version %LATEST_TAG% " docs\ReleaseNotes.md >nul
    if errorlevel 1 (
        echo ======================================================================
        echo BUILD BLOCKED - release notes not rolled over after %LATEST_TAG%.
        echo   docs\ReleaseNotes.md has no frozen "## Version %LATEST_TAG%" entry,
        echo   so the top placeholder section still holds already-shipped content.
        echo   Freeze the current top section as "## Version %LATEST_TAG%" and add
        echo   a fresh placeholder section for the new version before building.
        echo ======================================================================
        exit /b 1
    )
)

set version=%version%.%version_build%
echo Creating installer for version %version%
pyinstaller -y packaging\guitar-tap.spec
if errorlevel 1 (
    echo Running pyinstaller failed
    exit /b 1
)

REM ===============================================
REM Prepare installer path
REM ===============================================
set "installer_file=%cd%\packaging\guitar-tap.iss"
set "ISCC_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

REM ===============================================
REM You must install Inno Setup 6 to build the installer
REM ===============================================
"%ISCC_PATH%" "/DMyAppVersion=%version%" /F "%installer_file%"
if errorlevel 1 (
    echo Creating the installer failed
    exit /b 1
)
echo Installer created successfully

