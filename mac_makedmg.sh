#!/bin/sh
test -f "Guitar Tap.dmg" && rm "Guitar Tap.dmg"

# Create the dmg.
echo "Creating DMG"
create-dmg \
  --volname "Guitar Tap 0.7 Install" \
  --background "icons/guitar-tap-dmg.png" \
  --window-pos 1 1 \
  --icon "Guitar Tap.app" 190 350 \
  --window-size 640 535 \
  --icon-size 110 \
  --icon "Applications" 110 110 \
  --hide-extension "Applications" \
  --app-drop-link 450 360 \
  --format ULFO \
  --hdiutil-verbose \
  --volicon "icons/guitar-tap.icns" \
  "Guitar Tap.dmg" \
  "dist/"

echo "Signing DMG"
/usr/bin/codesign -s "Developer ID Application: David Smith (43QHHT3XK2)" "Guitar Tap.dmg"

echo "Done Creating DMG"
