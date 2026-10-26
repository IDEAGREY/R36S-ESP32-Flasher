# Add custom firmware

The custom firmware scanner accepts **one app-only `.bin` for the classic
ESP32**. It writes at `0x10000`, after checking that the ESP32 has a valid app
partition at that address and that the image fits. It then runs esptool's
`verify_flash` against the same file. Baud is fixed at 115200.

## Before copying a file

1. Get the firmware from the board maker or project's official release page.
2. Confirm it targets the classic ESP32 (`ESP32` / Xtensa LX6), not ESP32-S2,
   ESP32-S3, ESP32-C3, ESP32-C6, ESP8266, or another chip.
3. Confirm the release provides a **single app-partition image** intended for
   address `0x10000`. A generic `.bin` extension does not prove the file is
   compatible.
4. Check that the firmware is built for your exact board and its partition
   layout. This matters for boards with displays, touchscreens, unusual PSRAM,
   or custom pin assignments.

The custom file path does not support merged images, complete flash dumps,
bootloaders, partition tables, factory installers, or firmware that requires
multiple files or multiple flash addresses. Do not rename those files to make
them appear compatible. Use a board-specific flashing method for them.

The included **MicroPython Full Erase** image is handled as a separate,
recognized install: it erases the complete flash, checks for at least 4 MB,
and writes its own supported layout. Arbitrary custom full-flash images are
not supported.

## Copy and flash

1. Shut down the R36S and put its ArkOS card in your computer.
2. Open the card's **BOOT** partition. Create this folder if needed:

   ```text
   BOOT/ESP32-Firmware/
   ```

3. Copy the compatible app-only `.bin` into that folder. For example:

   ```text
   BOOT/ESP32-Firmware/MyBoardFirmware.bin
   ```

4. Safely eject the card, return it to the R36S, and boot ArkOS.
5. Connect the ESP32 through the R36S OTG port. Open **Ports → R36S ESP-32
   Flasher**, press **X** to rescan, select the file, and press **A**.
6. Leave the board connected until the flasher reports **FLASH VERIFIED**.
   Press **Y** for the serial Logs page; start listening with **A** and reset
   the ESP32 to capture its runtime output. Firmware may not emit readable
   serial logs.

## Board support

The ESP32-based CYD family often uses the classic ESP32 chip, but CYD screen and
touch firmware is board-specific. This flasher only handles a single app image
at `0x10000`; it will reject a CYD package that needs a bootloader, partition
table, multiple images, or a different address. The flasher does not configure
the display or touch hardware and cannot turn firmware for another board into
a compatible CYD build.
