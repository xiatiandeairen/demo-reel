#!/bin/bash
# Safety net: removes any DerivedData folder that xcodebuild made for this demo in ~/Library (the scenes
# pass -derivedDataPath, so normally there is none), and only those: each folder under
# ~/Library/Developer/Xcode/DerivedData whose recorded workspace lies inside $1.
demo=${1:?workdir}
real=$(cd "$demo" 2>/dev/null && pwd -P) || exit 0
for d in "$HOME"/Library/Developer/Xcode/DerivedData/*/; do
  p=$(/usr/libexec/PlistBuddy -c "Print :WorkspacePath" "$d/info.plist" 2>/dev/null) || continue
  case "$p" in "$demo"/*|"$real"/*) rm -rf "$d" ;; esac
done
exit 0
