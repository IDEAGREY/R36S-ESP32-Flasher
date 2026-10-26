#!/usr/bin/env bash
set -euo pipefail
PKG="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEST_BASE="${R36S_PORTS_DIR:-/roms/ports}"
if [[ ! -d "$DEST_BASE" && -d /storage/roms/ports ]]; then DEST_BASE=/storage/roms/ports; fi
if [[ ! -d "$DEST_BASE" ]]; then
  echo "Ports folder not found. Boot ArkOS once, then run this installer again." >&2
  exit 1
fi
command -v python3 >/dev/null 2>&1 || { echo 'Python 3 is required.' >&2; exit 1; }
DEST="$DEST_BASE/R36S-ESP32-Flasher"
STAGE="$(mktemp -d "$DEST_BASE/.r36s-esp32-stage.XXXXXXXX")"
PREV=''
cleanup() { rm -rf "$STAGE"; if [[ -n "$PREV" && -d "$PREV" && ! -d "$DEST" ]]; then mv "$PREV" "$DEST"; fi; }
trap cleanup EXIT
cp -a "$PKG/app.py" "$PKG/assets" "$PKG/engine" "$PKG/firmware" "$PKG/install" "$STAGE/"
mkdir -p "$STAGE/firmware/user"
if [[ -d "$DEST/firmware/user" ]]; then cp -a "$DEST/firmware/user/." "$STAGE/firmware/user/"; fi
if [[ -d "$DEST" ]]; then
  PREV="$DEST_BASE/.r36s-esp32-previous.$$"
  mv "$DEST" "$PREV"
fi
mv "$STAGE" "$DEST"
if [[ -n "$PREV" ]]; then rm -rf "$PREV"; fi
PREV=''
chmod 755 "$DEST/engine/bin/esptool"
LAUNCHER="$DEST_BASE/R36S-ESP-32-Flasher.sh"
TEMP_LAUNCHER="$DEST_BASE/.r36s-esp32-launcher.$$"
{
  printf '#!/usr/bin/env bash\nset -e\n'
  printf 'cd %q\n' "$DEST"
  printf 'exec python3 app.py\n'
} > "$TEMP_LAUNCHER"
chmod 755 "$TEMP_LAUNCHER"
mv -f "$TEMP_LAUNCHER" "$LAUNCHER"

# Install the CP210x access rule so the Ports app can use the USB adapter.
if command -v udevadm >/dev/null 2>&1; then
  if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
    install -m 0644 "$DEST/install/99-r36s-esp32-cp210x.rules" /etc/udev/rules.d/99-r36s-esp32-cp210x.rules
    udevadm control --reload-rules
    udevadm trigger --action=change --subsystem-match=tty || true
  elif command -v sudo >/dev/null 2>&1; then
    sudo install -m 0644 "$DEST/install/99-r36s-esp32-cp210x.rules" /etc/udev/rules.d/99-r36s-esp32-cp210x.rules
    sudo udevadm control --reload-rules
    sudo udevadm trigger --action=change --subsystem-match=tty || true
  else
    echo 'Installed app; CP210x access still needs administrator permission setup.' >&2
  fi
fi
echo "Installed: $LAUNCHER"
echo 'Copy future .bin files to /boot/ESP32-Firmware/; press X in the app to refresh.'
