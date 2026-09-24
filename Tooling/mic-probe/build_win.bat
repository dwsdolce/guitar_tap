@echo off
REM Build GuitarTapMicProbe.exe — a single-file console exe for users to run.
REM Uses the release .venv so the exe carries the SAME sounddevice/PortAudio DLL
REM as the shipping Guitar Tap build.
cd /d "%~dp0\..\.."

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo Activating virtual environment failed
    exit /b 1
)

pyinstaller -y --onefile --console --name GuitarTapMicProbe ^
    --icon "%cd%\src\guitar_tap\icons\guitar-tap.ico" ^
    --exclude-module scipy --exclude-module PySide6 --exclude-module pyqtgraph ^
    --distpath dist\mic-probe --workpath build\mic-probe --specpath build\mic-probe ^
    Tooling\mic-probe\mic_probe.py
if errorlevel 1 (
    echo Running pyinstaller failed
    exit /b 1
)
echo Built dist\mic-probe\GuitarTapMicProbe.exe
