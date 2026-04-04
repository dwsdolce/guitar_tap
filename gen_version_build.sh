#!/bin/sh
# gen_version_build.sh
#
# Writes the current git commit count to 'version_build'.
# This file is read by _version.py at runtime to populate the build number,
# mirroring Xcode's CFBundleVersion stamped from the git commit count.
#
# Usage:
#   ./gen_version_build.sh           # writes version_build in the current directory
#   source gen_version_build.sh      # same, but also exports VERSION_BUILD to the shell
#
# The generated file is not committed to git (add 'version_build' to .gitignore).

build_number=$(git rev-list --count HEAD)
if [ $? -ne 0 ]; then
    echo "gen_version_build.sh: git rev-list failed — is this a git repository?" >&2
    exit 1
fi

printf '%s' "$build_number" > version_build
echo "gen_version_build.sh: version_build = $build_number"
export VERSION_BUILD="$build_number"
