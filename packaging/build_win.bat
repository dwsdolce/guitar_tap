
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

