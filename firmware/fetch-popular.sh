#!/usr/bin/env bash
# Re-fetch pinned upstream release images and verify their published SHA-256.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
OUT="$ROOT/firmware/official"
mkdir -p "$OUT"
fetch() {
  local url="$1" file="$2" sha="$3"
  if command -v curl >/dev/null 2>&1; then curl -fL --retry 2 "$url" -o "$OUT/$file"
  else wget -O "$OUT/$file" "$url"
  fi
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s  %s\n' "$sha" "$OUT/$file" | sha256sum -c -
  else
    printf '%s  %s\n' "$sha" "$OUT/$file" | shasum -a 256 -c -
  fi
}
fetch 'https://github.com/wled/WLED/releases/download/v16.0.1/WLED_16.0.1_ESP32.bin' \
  'WLED_16.0.1_ESP32.bin' '628917b0753edcfc9a8408e6387c6d1ace6a360d315441e9563d60299fef8594'
fetch 'https://www.micropython.org/resources/firmware/ESP32_GENERIC-20260824-v1.29.0.bin' \
  'MicroPython_FullErase_v1.29.0.bin' 'e67ad6015a0a504c1fec9aa9bbf589d0432ed28e62546f4f8dd8a147f8bd95f6'
