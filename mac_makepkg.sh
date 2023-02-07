#!/bin/sh
test -f "Guitar Tap.pkg" && rm "Guitar Tap.pkg"
# Create the pkg.
productbuild --sign "Developer ID Installer: David Smith (43QHHT3XK2)" --component dist/Guitar\ Tap.app /Applications Guitar\ Tap.pkg
