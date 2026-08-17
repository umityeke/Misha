#!/bin/bash
set -euo pipefail

bundle_path="${1:-}"
signing_identity="${2:--}"
entitlements_path="${3:-packaging/macos/entitlements.plist}"

if [[ -z "$bundle_path" || "$bundle_path" != */Misha.app || ! -d "$bundle_path/Contents" ]]; then
  echo "Expected an existing absolute or relative path ending in Misha.app" >&2
  exit 2
fi
if [[ ! -f "$entitlements_path" ]]; then
  echo "Entitlements file is missing" >&2
  exit 2
fi

while IFS= read -r -d '' candidate; do
  if file -b "$candidate" | grep -q 'Mach-O'; then
    codesign --force --options runtime --sign "$signing_identity" "$candidate"
  fi
done < <(find "$bundle_path/Contents/Frameworks" "$bundle_path/Contents/MacOS" -type f -print0)

codesign --force --options runtime --entitlements "$entitlements_path" \
  --sign "$signing_identity" "$bundle_path"
codesign --verify --deep --strict "$bundle_path"
codesign -dvv "$bundle_path" 2>&1 | grep -q 'runtime'
