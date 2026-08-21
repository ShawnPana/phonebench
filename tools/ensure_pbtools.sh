#!/bin/bash
# Build + install + grant PBTools on the booted sim. Idempotent, CI-safe.
set -e
cd "$(dirname "$0")"
if [ ! -f pbcontacts ] || [ pbcontacts.m -nt pbcontacts ]; then
  SDK=$(xcrun -sdk iphonesimulator --show-sdk-path)
  xcrun -sdk iphonesimulator clang -fobjc-arc -fmodules -isysroot "$SDK" \
    -framework Contacts -framework Foundation -o pbcontacts pbcontacts.m
fi
cp -f pbcontacts PBTools.app/
xcrun simctl install booted PBTools.app
xcrun simctl privacy booted grant contacts com.phonebench.tools
xcrun simctl privacy booted grant reminders com.phonebench.tools
echo "pbtools ready"
