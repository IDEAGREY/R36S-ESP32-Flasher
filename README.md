# R36S ESP-32 Flasher

A standalone ArkOS Ports app for flashing supported firmware to **classic
ESP32** boards from an R36S. The project bundles its flasher and serial
dependencies; it does not need an internet connection on the handheld.

The interface includes a firmware progress/log screen and a **Logs** page that
reads live UART output from the ESP32 at 115200 baud. The flash screen's
`FLASH VERIFIED` result is the byte-for-byte flash check. The Logs page shows
runtime output only when the installed firmware emits readable serial text.

## Compatibility

- Requires an R36S (or compatible R3XS handheld) running ArkOS, a microSD card,
  and a USB-C OTG adapter.
- Supports the **classic ESP32** chip family (`ESP32` / Xtensa LX6), using a
  USB data cable and a USB-to-serial adapter such as CP210x, CH340, or FTDI.
- Does not support ESP32-S2, ESP32-S3, ESP32-C3, ESP32-C6, ESP8266, or other
  chip families. The flasher fixes the baud rate at 115200.
- A board can contain a classic ESP32 and still need firmware made specifically
  for that board. CYD boards commonly use a classic ESP32, but this app does not
  make arbitrary CYD firmware compatible: it accepts app-only images for the
  app partition at `0x10000`, and the firmware must match the CYD display,
  touch, and pin layout. Merged images and multi-file board installers are not
  supported.

## R36MAX & dArkOS (`arkos4clone`) compatibility

This flasher runs natively on both the **R36MAX (720×720 1:1 IPS)** and the **R36S / R33S / R35S / R36H (640×480 4:3)**:

- **Adaptive 720×720 & 640×480 layout:** Automatically detects the R36MAX's 720×720 square display via `SDL_GetRendererOutputSize` and `/sys/class/graphics/fb0/virtual_size`, expanding the UI to 9 visible firmware rows and 23 serial log lines while keeping nearest-neighbor crisp bitmap text (`SDL_RENDER_SCALE_QUALITY=0`).
- **dArkOS (`arkos4clone`) & dual-SD (`TF2`) support:** `install.sh` automatically targets `/roms2/ports` when a second microSD card is active, or `/roms/ports` on single-card setups, and loads `/opt/inttools/gamecontrollerdb.txt` (or `/usr/share/gamecontrollerdb.txt`) so all R36MAX gamepad controls and `Select + Start` work out of the box.
- **SSH quick install (R36MAX / dArkOS with Wi-Fi or USB Ethernet):**
  ```bash
  scp R36S-ESP32-Flasher-0.2.0.zip ark@<handheld-ip>:/home/ark/
  ssh ark@<handheld-ip> "unzip -qo ~/R36S-ESP32-Flasher-0.2.0.zip -d ~ && bash ~/R36S-ESP32-Flasher/install.sh"
  ```
  Then restart EmulationStation (`sudo systemctl restart emulationstation` or reboot) and open **Ports → R36S ESP-32 Flasher**.

## 1. Prepare an ArkOS / dArkOS microSD card

The card must already have a working ArkOS installation before installing this
Ports app. A blank card will not show Ports.

1. Download the latest compatible **R33S / R35S / R36S / R36H multipanel**
   ArkOS image from the [AeolusUX ArkOS-R3XS releases](https://github.com/AeolusUX/ArkOS-R3XS/releases).
   Do not choose the R36S Plus image for a standard R36S.
2. If the download is split into `.7z.001` and `.7z.002` parts, download every
   part into the same folder and extract the archive with 7-Zip. Do not rename
   the parts.
3. Use [balenaEtcher](https://etcher.balena.io/) to select the extracted ArkOS
   image, select the microSD card, and choose **Flash**. This erases the card.
4. Eject the card, put it in the R36S's OS/TF1 slot, and start the handheld.
   Let ArkOS finish its first-boot setup and any automatic reboot. Shut down
   ArkOS normally before removing the card.

Use a reliable card and keep a separate backup of anything you want to retain.

## 2. Copy this project onto the card

On GitHub, choose **Code → Download ZIP** and extract it. GitHub names the
extracted folder `R36S-ESP32-Flasher-main`; rename that folder to
`R36S-ESP32-Flasher`. Insert the ArkOS card into a computer and open its small
**BOOT** partition. Copy the entire project folder into the root of BOOT. The
result must be:

```text
BOOT/
└── R36S-ESP32-Flasher/
    ├── install.sh
    ├── app.py
    ├── engine/
    └── firmware/
```

On macOS, if BOOT is mounted at `/Volumes/BOOT` and the extracted project is in
Downloads, this copies it:

```bash
ditto "$HOME/Downloads/R36S-ESP32-Flasher" "/Volumes/BOOT/R36S-ESP32-Flasher"
```

Safely eject the card from the computer and put it back in the R36S.

## 3. Install the Ports entry

The R36S OTG port is shared by the keyboard and the ESP32 connection. **Unplug
the ESP32 while using the keyboard.** Connect a USB keyboard through the OTG
adapter.

1. Boot into EmulationStation.
2. Press **START → Quit → Quit Emulationstation**.
3. Press **Alt+F2** if the terminal login is not already visible.
4. Log in with username `ark` and password `ark`.
5. Type this command and press Enter:

   ```bash
   bash /boot/R36S-ESP32-Flasher/install.sh
   ```

6. When it says `Installed: ...`, type this to restart EmulationStation. If
   `sudo` asks for a password, type `ark` and press Enter (the password stays
   invisible while typing):

   ```bash
   sudo systemctl restart emulationstation
   ```

The terminal closes as EmulationStation starts. After it returns, find
**Ports → R36S ESP-32 Flasher**. If Ports does not appear, confirm the installer
printed `Installed`, then restart EmulationStation with the command above.

## 4. Flash firmware

1. Connect the ESP32 to the R36S OTG adapter with a **USB data cable**. Remove
   the keyboard first. The board must have a USB-to-serial interface; charging-
   only cables will not work.
2. Open **Ports → R36S ESP-32 Flasher**. The left status should show USB ready.
   Use **L/R** to cycle detected serial ports if more than one is listed.
3. Use **Up/Down** to select firmware. The right panel shows the target and
   image size. Press **A** to flash an app-only image.
4. Keep the ESP32 connected until the progress screen reports
   **FLASH VERIFIED**. That means esptool compared the written image with the
   selected file. App-only flashing preserves the bootloader, partition table,
   and other flash contents.
5. **MicroPython Full Erase** is different: press **A twice** when prompted.
   It erases the ESP32's entire flash before installing and replaces existing
   firmware and data.

## 5. View ESP32 serial logs

1. In the flasher, press **Y** to open **ESP32 Serial Logs**.
2. Press **A** to start or stop listening at **115200 baud**. Press **X** to
   clear the visible log, **Up/Down** to scroll, **L/R** to choose a port, and
   **B** or **Left** to return to firmware.
3. After starting the listener, press the ESP32 board's **RESET/EN** button to
   capture its boot messages. Keep it connected while viewing logs.

The flash progress screen provides the write and verification result. Serial
logs are extra runtime evidence, but some firmware prints no readable UART
messages, and a quiet Logs page does not mean the flash failed. The handheld
does not decode or interpret firmware-specific log formats.

## Controls and exit

| Input | Action |
| --- | --- |
| Up / Down | Select firmware or scroll serial logs |
| A | Flash selected firmware; on Logs, start/stop serial listening |
| Y | Open/close Logs |
| X | Rescan firmware; on Logs, clear visible logs |
| L / R | Change detected USB serial port |
| B / Left | Return from Logs to firmware |
| START | Options menu; choose Exit to EmulationStation |

From a terminal, return to EmulationStation with:

```bash
sudo systemctl restart emulationstation
```

## Add custom firmware

See [CUSTOM-FIRMWARE.md](CUSTOM-FIRMWARE.md) for the supported image format,
copy location, and custom firmware steps. Upstream sources and checksums for
the bundled firmware are listed in [firmware/UPSTREAM.md](firmware/UPSTREAM.md).
