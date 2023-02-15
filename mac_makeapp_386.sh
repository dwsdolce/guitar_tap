#!/bin/bash
echo "Running pyinstaller"
pyinstaller -y guitar-tap-386.spec
echo "Removing dist/guitar-tap"
rm -rf dist/guitar-tap
