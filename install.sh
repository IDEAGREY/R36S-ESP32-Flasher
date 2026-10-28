#!/usr/bin/env bash
set -euo pipefail

PKG="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEST_BASE="${R36S_PORTS_DIR:-}"
if [[ -z "$DEST_BASE" ]]; then
  if [[ -d /roms2/ports ]]; then
    DEST_BASE=/roms2/ports
  elif [[ -d /roms/ports ]]; then
    DEST_BASE=/roms/ports
  elif [[ -d /storage/roms/ports ]]; then
    DEST_BASE=/storage/roms/ports
  else
    DEST_BASE=/roms/ports
  fi
fi
if [[ ! -d "$DEST_BASE" ]]; then
  echo "Ports folder not found (/roms/ports or /roms2/ports). Boot ArkOS/dArkOS once, then run this installer again." >&2
  exit 1
fi
command -v python3 >/dev/null 2>&1 || { echo 'Python 3 is required.' >&2; exit 1; }

MODEL="$( { tr -d '\0' < /proc/device-tree/model; } 2>/dev/null || echo 'RK3326 Handheld' )"
FB="$(cat /sys/class/graphics/fb0/virtual_size 2>/dev/null | tr , x || echo 'auto')"
echo "Detected device: $MODEL (framebuffer: $FB)"

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
chmod 755 "$DEST/engine/bin/esptool" 2>/dev/null || true

LAUNCHER="$DEST_BASE/R36S-ESP-32-Flasher.sh"
TEMP_LAUNCHER="$DEST_BASE/.r36s-esp32-launcher.$$"
{
  printf '#!/usr/bin/env bash\nset -e\n'
  printf 'cd %q\n' "$DEST"
  printf 'for db in /opt/inttools/gamecontrollerdb.txt /usr/share/gamecontrollerdb.txt; do\n'
  printf '  [ -f "$db" ] && export SDL_GAMECONTROLLERCONFIG_FILE="$db" && break\n'
  printf 'done\n'
  printf 'export PYTHONUNBUFFERED=1\n'
  printf 'python3 app.py >> "$PWD/launch.log" 2>&1\n'
  printf 'CODE=$?\n'
  printf 'sync\n'
  printf 'printf "\\033c" > /dev/tty1 2>/dev/null || true\n'
  printf 'exit $CODE\n'
} > "$TEMP_LAUNCHER"
chmod 755 "$TEMP_LAUNCHER" 2>/dev/null || true
mv -f "$TEMP_LAUNCHER" "$LAUNCHER"

# Ensure dialout group membership and udev USB-serial rules (CP210x, CH34x, FTDI, PL2303, Espressif)
TARGET_USER="${SUDO_USER:-${USER:-ark}}"
if command -v usermod >/dev/null 2>&1; then
  if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
    usermod -aG dialout "$TARGET_USER" 2>/dev/null || true
  elif command -v sudo >/dev/null 2>&1; then
    sudo usermod -aG dialout "$TARGET_USER" 2>/dev/null || true
  fi
fi

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
    echo 'Installed app; USB serial access still needs administrator permission setup.' >&2
  fi
fi

echo "Installed: $LAUNCHER"
echo 'Copy future .bin files to /boot/ESP32-Firmware/ or /roms/ESP32-Firmware/; press X in the app to refresh.'
