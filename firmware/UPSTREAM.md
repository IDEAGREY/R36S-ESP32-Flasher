# Included firmware

The firmware list contains three ready-to-flash images. SIGINT and WLED are
app-only writes at `0x10000`; the app checks the existing partition table and
app slot before writing, then verifies the result. MicroPython replaces the
entire ESP32 flash: it requires at least 4 MB, asks for a second A press, erases
the device, writes at `0x1000`, and verifies the image.

| App label | Board | Size | Source | SHA-256 |
| --- | --- | ---: | --- | --- |
| SIGINT ESP32 Link | Classic ESP32 Dev Module | 1,017,344 bytes | Prebuilt companion image from this project | `78c7f4b1c652e519995acfb4e338d2334659052cc7fdf5f3a0c58b9d14024ea4` |
| WLED 16.0.1 | Classic ESP32 | 1,304,720 bytes | [WLED v16.0.1](https://github.com/wled/WLED/releases/tag/v16.0.1) | `628917b0753edcfc9a8408e6387c6d1ace6a360d315441e9563d60299fef8594` |
| MicroPython Full Erase 1.29.0 | Classic ESP32 with at least 4 MB flash | 1,789,952 bytes | [Official ESP32_GENERIC release](https://www.micropython.org/download/ESP32_GENERIC/) | `e67ad6015a0a504c1fec9aa9bbf589d0432ed28e62546f4f8dd8a147f8bd95f6` |

MicroPython is bundled under the name `MicroPython_FullErase_v1.29.0.bin` to
make its destructive full-device install clear in the file list. It is the
official ESP32_GENERIC image; no second MicroPython image is bundled. Extra
MicroPython images placed in user firmware folders are hidden to keep the
selection limited to this known full-erase image.

WLED is licensed under EUPL-1.2; its license text is included in
`firmware/source/WLED-LICENSE.txt`, and its upstream source is at the linked
v16.0.1 tag. MicroPython is MIT-licensed and its license text is included in
`firmware/source/MicroPython-LICENSE.txt`. The app supports extra app-only
`.bin` files copied to `/boot/ESP32-Firmware/`. It does not build Arduino
sketches.
