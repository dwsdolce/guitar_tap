# guitar_tap
 Capture and analyze guitar top and back resonances using an impulse response from tap testing.
 The motivation for this software comes from Trevor Gore and his work on defining methods and tools to improve reproducibility in building guitars.
 The primary reference is Contemporary Acoustic Guitar Design and Build by Trevor Gore in collaboration with Gerard Gilet.
 
 This software is written in Python 3 and can be run on any platform that supports Python and the required packages.

 ## Running from Installer:
 There is an installer for MAC OS and for Windows in the directory: https://github.com/dwsdolce/guitar_tap/releases.
 Please note that the MAC installer will only run on systems newer than Big Sur (11.0). This is due to the end of life of
 the earlier systems
 
 ## To run this software from source:

 ### 1. Prerequisites
 * Install Python 3.14 or later from https://www.python.org/ (`python3` / `pip3` on macOS and most Linux distros).
 * Install Git and clone the repository:
	- `git clone https://github.com/dwsdolce/guitar_tap`
	- `cd guitar_tap`

 ### 2. System dependencies

 **macOS:**
	- `brew install portaudio`

 **Linux (Debian/Ubuntu):**
	- `sudo apt update`
	- `sudo apt install portaudio19-dev libxcb-cursor-dev`

 **Windows:** no extra system packages required.

 ### 3. Create a virtual environment (recommended)
	- `python3.14 -m venv .venv`
	- Activate it:
	  - Linux/macOS: `source .venv/bin/activate`
	  - Windows (PowerShell): `.\.venv\Scripts\Activate.ps1`
	  - Windows (Cygwin bash): `source .venv/Scripts/activate` (note: `Scripts`, not `bin`, even from bash)

 ### 4. Install the project
 All dependencies (runtime + optional extras) are declared in [pyproject.toml](pyproject.toml).

 * Run-only install:
	- Linux/Windows: `pip install -e .`
	- macOS: `pip install -e ".[macos]"`

 * Developer install (adds pytest, mypy, ruff, weasyprint):
	- `pip install -e ".[dev]"` (add `,macos` on macOS)

 * Launch the app:
	- `python -m guitar_tap`

 ## Building installers

 Install the packaging extras (adds PyInstaller):
	- `pip install -e ".[packaging]"` (combine extras as needed, e.g. `".[dev,packaging]"`)

 Then run the platform script from the repository root:
	- Linux:   `./packaging/build_linux`
	- macOS:   `./packaging/build_mac`
	- Windows: `packaging\build_win.bat`

 ### Platform-specific tooling

 **Linux (AppImage):** the build script invokes `appimagetool`. Install it once:
	- `wget -O ~/bin/appimagetool https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage`
	- `chmod +x ~/bin/appimagetool`
	- If `appimagetool` is elsewhere, set `APPIMAGETOOL=/path/to/appimagetool` before running `build_linux`.
	- On Ubuntu 22.04+ you may also need `sudo apt install libfuse2` for `appimagetool` to run.
	- For broadest compatibility, build inside a container running the oldest glibc you want to support (e.g. Ubuntu 22.04 LTS).

 **Windows:** the installer step uses [Inno Setup](https://jrsoftware.org/isinfo.php) — install it and ensure `iscc.exe` is on `PATH`. Code signing requires the signing certificate referenced in the script.

 **macOS:** code signing and notarization require an Apple Developer ID. The spec file ([packaging/guitar-tap.spec](packaging/guitar-tap.spec)) references the certificate identity — adjust it for your own developer account.
