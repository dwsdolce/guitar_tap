# guitar_tap
 Capture and analyze guitar top and back resonances using an impulse response from tap testing.
 The motivation for this software comes from Trevor Gore and his work on defining methods and tools to improve reproducibility in building guitars.
 The primary reference is Contemporary Acoustic Guitar Design and Build by Trevor Gore in collaboration with Gerard Gilet.
 
 This software is written in Python 3 and can be run on any platform that supports Python and the required packages.

 ## Running from Installer:
 There is an installer for MAC OS and for Windows in the directory: https://github.com/dwsdolce/guitar_tap/releases.
 Please note that the MAC installer will only run on systems newer than Big Sur (11.0). This is due to the end of life of
 the earlier systems
 
 ## Required packages to run from Source code
 * numpy
 * scipy
 * pyaudio
 * pyqt6
 * matplotlib
 * pyobjc (on MAC only)

 ## To run this software from source:
 * Download the source code or clone the repository from https://github.com/dwsdolce/guitar_tap
 * Install python from https://www.python.org/ (the latest python is preferred 3.11).
 * Open a cmd window or shell/terminal that can run python

 * For Windows or Linux
 	- pip install numpy scipy pyaudio pyqt6 matplotlib
	- python guitar_tap.py

 * For MAC
 	- pip install numpy scipy pyaudio pyqt6 matplotlib
	- pip install pyobjc==8.5.1
	- python guitar_tap.py

 **NOTE:** You may have to use python3 and pip3 on your system (MAC requires this).  
 **NOTE:** On MAC, before running pip you need to:
- brew install portaudio
