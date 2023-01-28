#!/bin/sh
test -f "Guitar Tap.dmg" && rm "Guitar Tap.dmg"
test -d "dist/dmg" && rm -rf "dist/dmg"
# Make the dmg folder & copy our .app bundle in.
mkdir -p "dist/dmg"
cp -r "dist/Guitar Tap.app" "dist/dmg"
# Create the dmg.
create-dmg \
--volname "Guitar Tap" \
--volicon "icons/guitar-tap.icns" \
--window-pos 200 120 \
--window-size 800 400 \
--icon-size 100 \
--icon "Guitar Tap.app" 200 190 \
--hide-extension "Guitar Tap.app" \
--app-drop-link 600 185 \
"Guitar Tap.dmg" \
"dist/dmg/"
