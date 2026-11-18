#!/bin/bash
set -euo pipefail

source_dir="$(cd "$(dirname "$0")" && pwd)"
app_dir="${1:-$source_dir/../.pio/mac/Stackchan Strider.app}"

mkdir -p "$app_dir/Contents/MacOS"
cp "$source_dir/Info.plist" "$app_dir/Contents/Info.plist"
xcrun swiftc -O -framework AppKit -framework CoreBluetooth \
    "$source_dir/main.swift" -o "$app_dir/Contents/MacOS/Strider"
/usr/bin/codesign --force --sign - "$app_dir"
printf '%s\n' "$app_dir"
