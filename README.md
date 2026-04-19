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
 * Download the source code or clone the repository from https://github.com/dwsdolce/guitar_tap
 * Install Python 3.14 or later from https://www.python.org/
 * Open a terminal (or cmd/PowerShell on Windows)

 **NOTE:** On MAC, install portaudio first:
	- brew install portaudio

 **NOTE:** On Linux, install system dependencies first:
	- sudo apt update
	- sudo apt install portaudio19-dev
	- sudo apt-get install -y libxcb-cursor-dev

 * For Windows and Linux — from the repository root:
	- pip install -e .
	- python guitar_tap.py

 * For MAC — from the repository root:
	- pip install -e ".[macos]"
	- python guitar_tap.py

 **NOTE:** You may have to use `python3` and `pip3` on your system (MAC requires this).

 * To build an installer you need to:
	- pip install pyinstaller
	- build_{linux, mac, win}

 **NOTE:**  For Windows and MACOS there are additional packages required for signing the installer. See the scripts.
