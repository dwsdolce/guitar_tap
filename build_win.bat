
@echo off
REM ===============================================
REM  Setup the correct python environment
REM ===============================================
REM Activating Windows virtual environment for Python
echo "Activating win virtual environment for Python"
call ".venv\Scripts\activate.bat"

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
REM Run pyinstaller
REM ===============================================
REM Get the product version
set /p version=<version
echo Creating installer for version %version%
pyinstaller -y guitar-tap.spec
if errorlevel 1 (
    echo Running pyinstaller failed
    exit /b 1
)

REM ===============================================
REM Prepare installer path
REM ===============================================
set "installer_file=%cd%\guitar-tap.iss"

REM ===============================================
REM You must install Inno Setup 6 to build the installer
REM ===============================================
set "ISCC_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
"%ISCC_PATH%" /DMyAppVersion=%version% /F "%installer_file%"
if errorlevel 1 (
    echo Creating the installer failed
    exit /b 1
)
echo Installer created successfully

