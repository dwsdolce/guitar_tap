#!/bin/bash
echo "Running pyinstaller"
pyinstaller -y guitar-tap.spec
echo "Removing dist/guitar-tap"
rm -rf dist/guitar-tap
