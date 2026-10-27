# Changelog

## 0.2.0

- **R36MAX (720×720 1:1 IPS) native compatibility:**
  - Automatically detects the R36MAX's 720×720 square display (`SDL_GetRendererOutputSize` and `/sys/class/graphics/fb0/virtual_size`) while preserving the 640×480 4:3 layout on standard R36S panels.
  - Expands the R36MAX view to show 9 firmware rows, 23 serial monitor lines, and 16 flash progress log lines with nearest-neighbor bitmap font scaling (`SDL_RENDER_SCALE_QUALITY=0`).
  - Auto-loads the firmware's SDL2 controller mapping database (`/opt/inttools/gamecontrollerdb.txt` or `/usr/share/gamecontrollerdb.txt`) and adds `Select + Start` quick-exit support plus R36MAX raw joystick D-pad fallbacks.
- **Dual-SD (`/roms2/ports`) and exFAT reliability:**
  - `install.sh` now detects `/roms2/ports` (TF2 card on R36MAX / ArkOS / dArkOS) automatically alongside `/roms/ports` and `/storage/roms/ports`.
  - Runs the bundled `esptool` via `python3 -m esptool` with `PYTHONPATH` so flashing never fails with `Permission denied` on `noexec`/`fmask` FAT32 or exFAT SD partitions.
  - Scans `/roms/ESP32-Firmware`, `/roms2/ESP32-Firmware`, and `~/ESP32-Firmware` in addition to `/boot/ESP32-Firmware`.
  - Adds Espressif native USB (`303a`) to the udev serial access rules and adds the user to the `dialout` group.
- **CI tag release workflow & headless geometry tests:**
  - Added `.github/workflows/tests.yml` and `.github/workflows/release.yml` to verify firmware SHA-256 digests, run headless 640×480 and 720×720 layout & input smoke tests, and publish `R36S-ESP32-Flasher-<version>.zip` on `v*` tags.
