#!/usr/bin/env python3
"""Standalone R36S ESP-32 firmware flasher."""
import ctypes as C
import ctypes.util
import glob
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

W, H = 640, 480
ROOT = Path(__file__).resolve().parent
COLORS = {
    'bg': (231, 235, 242), 'panel': (250, 251, 253), 'white': (255, 255, 255),
    'line': (136, 151, 171), 'ink': (18, 29, 45), 'muted': (55, 70, 91),
    'blue': (18, 70, 151), 'blue2': (26, 105, 196), 'select': (204, 226, 251),
    'green': (20, 151, 80), 'greenbg': (188, 244, 203), 'red': (187, 54, 48),
    'amber': (171, 102, 10), 'black': (8, 16, 28), 'grid': (207, 216, 228),
}
NOTICE = ''


def shorten(value, limit):
    value = str(value).replace('\n', ' ').replace('\r', ' ')
    return value if len(value) <= limit else value[:max(1, limit - 2)] + '..'


def serial_ports():
    paths = sorted(set(glob.glob('/dev/serial/by-id/*') + glob.glob('/dev/ttyUSB*') +
                       glob.glob('/dev/ttyACM*')))
    unique = {}
    for path in paths:
        unique.setdefault(os.path.realpath(path), path)
    return sorted(unique.values())


def esptool_path():
    bundled = ROOT / 'engine' / 'bin' / 'esptool'
    return str(bundled) if bundled.is_file() else (shutil.which('esptool') or shutil.which('esptool.py'))


def read_partitions(tool, port):
    """Read the partition table only; the flasher never erases or backs up flash."""
    global NOTICE
    with tempfile.TemporaryDirectory(prefix='r36s-esp32-') as temp:
        table = Path(temp) / 'partitions.bin'
        try:
            result = subprocess.run([tool, '--chip', 'esp32', '--port', port, '--baud', '115200',
                                     'read_flash', '0x8000', '0x1000', str(table)],
                                    capture_output=True, text=True, timeout=35)
        except subprocess.TimeoutExpired:
            NOTICE = 'NO BOOTLOADER REPLY  |  HOLD BOOT AND RETRY'
            return None
        except OSError as error:
            NOTICE = 'ESPTOOL ERROR: ' + shorten(error, 40)
            return None
        if result.returncode:
            message = (result.stderr or result.stdout).lower()
            if 'permission denied' in message or 'operation not permitted' in message:
                NOTICE = 'SERIAL PERMISSION DENIED  |  REINSTALL ACCESS RULE'
            elif 'failed to connect' in message or 'no serial data received' in message:
                NOTICE = 'NO BOOTLOADER REPLY  |  HOLD BOOT AND RETRY'
            else:
                NOTICE = shorten(result.stderr or result.stdout or 'PARTITION READ FAILED', 72)
            return None
        if not table.is_file():
            NOTICE = 'ESP32 PARTITION TABLE WAS NOT READ'
            return None
        raw = table.read_bytes()
        entries = []
        for offset in range(0, min(len(raw), 0xC00), 32):
            magic, ptype, _subtype, start, size = struct.unpack_from('<HBBII', raw, offset)
            if magic in (0xFFFF, 0xEBEB):
                break
            if magic != 0x50AA:
                NOTICE = 'NO VALID ESP32 PARTITION TABLE'
                return None
            label = raw[offset + 12:offset + 28].split(b'\0', 1)[0].decode('ascii', 'replace')
            entries.append((ptype, _subtype, start, size, label))
        if not entries:
            NOTICE = 'ESP32 PARTITION TABLE IS EMPTY'
            return None
        return entries


def connected_flash_bytes(tool, port):
    """Read the flash chip's reported capacity before any full-device write."""
    global NOTICE
    try:
        result = subprocess.run([tool, '--chip', 'esp32', '--port', port, '--baud', '115200',
                                 'flash_id'], capture_output=True, text=True, timeout=35)
    except (OSError, subprocess.TimeoutExpired):
        NOTICE = 'CANNOT IDENTIFY ESP32 FLASH CHIP'
        return None
    output = (result.stdout or '') + '\n' + (result.stderr or '')
    if result.returncode:
        NOTICE = shorten(result.stderr or result.stdout or 'FLASH CHIP CHECK FAILED', 72)
        return None
    match = re.search(r'Detected flash size:\s*(\d+)\s*(KB|MB)', output, re.IGNORECASE)
    if not match:
        NOTICE = 'FLASH SIZE UNKNOWN  |  FULL INSTALL STOPPED'
        return None
    multiplier = 1024 if match.group(2).upper() == 'KB' else 1024 * 1024
    return int(match.group(1)) * multiplier


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def catalog():
    path = ROOT / 'firmware' / 'catalog.json'
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def firmware_dirs():
    dirs = [ROOT / 'firmware' / 'official', ROOT / 'firmware' / 'user', Path('/boot/ESP32-Firmware'),
            Path('/boot/ESP32-Flasher'), Path('/roms/ports/R36S-ESP32-Flasher/firmware/user'),
            Path('/storage/roms/ports/R36S-ESP32-Flasher/firmware/user')]
    found = []
    for folder in dirs:
        try:
            resolved = folder.resolve()
            if resolved.is_dir() and resolved not in found:
                found.append(resolved)
        except OSError:
            pass
    return found


def list_firmware():
    files = {}
    hashes = set()
    pinned_micropython = (ROOT / 'firmware' / 'official' / 'MicroPython_FullErase_v1.29.0.bin').resolve()
    pinned_sigint = (ROOT / 'firmware' / 'official' / 'SIGINT_ESP32_Link.bin').resolve()
    for folder in firmware_dirs():
        try:
            candidates = [item for item in folder.rglob('*.bin')]
        except OSError:
            continue
        for path in candidates:
            try:
                if path.name.startswith('.'):
                    continue
                if path.is_file() and path.stat().st_size > 0:
                    resolved = path.resolve()
                    name = path.name.casefold()
                    # Keep only the known, ready-to-flash bundled releases.
                    if 'tasmota' in name:
                        continue
                    if ('micropython' in name or name.startswith('esp32_generic')) and resolved != pinned_micropython:
                        continue
                    if 'sigint' in name and resolved != pinned_sigint:
                        continue
                    digest = sha256_file(resolved)
                    if digest in hashes:
                        continue
                    hashes.add(digest)
                    files.setdefault(path.name.casefold(), resolved)
            except OSError:
                pass
    order = {'SIGINT_ESP32_Link.bin': 0, 'WLED_16.0.1_ESP32.bin': 1,
             'MicroPython_FullErase_v1.29.0.bin': 2}
    return sorted(files.values(), key=lambda item: (item.suffix.lower() != '.bin',
                                                   order.get(item.name, 10), item.name.lower()))


def port_name(port):
    if not port:
        return 'NO ESP32 CONNECTED'
    basename = Path(port).name
    if 'cp210' in port.lower():
        return 'CP210x  ' + basename
    if 'ch34' in port.lower():
        return 'CH34x  ' + basename
    return basename


class Rect(C.Structure):
    _fields_ = [('x', C.c_int), ('y', C.c_int), ('w', C.c_int), ('h', C.c_int)]


class Canvas:
    def __init__(self):
        lib = C.util.find_library('SDL2') or 'libSDL2-2.0.so.0'
        self.s = C.CDLL(lib)
        def proc(name, ret, args):
            fn = getattr(self.s, name); fn.restype = ret; fn.argtypes = args; return fn
        ptr, integer = C.c_void_p, C.c_int
        self.init = proc('SDL_Init', integer, [C.c_uint32])
        self.quit = proc('SDL_Quit', None, [])
        self.createwin = proc('SDL_CreateWindow', ptr, [C.c_char_p, integer, integer, integer, integer, C.c_uint32])
        self.renderer = proc('SDL_CreateRenderer', ptr, [ptr, integer, C.c_uint32])
        self.logical = proc('SDL_RenderSetLogicalSize', integer, [ptr, integer, integer])
        self.color = proc('SDL_SetRenderDrawColor', integer, [ptr, C.c_uint8, C.c_uint8, C.c_uint8, C.c_uint8])
        self.clear = proc('SDL_RenderClear', integer, [ptr])
        self.present = proc('SDL_RenderPresent', None, [ptr])
        self.fill = proc('SDL_RenderFillRect', integer, [ptr, C.POINTER(Rect)])
        self.draw = proc('SDL_RenderDrawRect', integer, [ptr, C.POINTER(Rect)])
        self.line = proc('SDL_RenderDrawLine', integer, [ptr, integer, integer, integer, integer])
        self.event = proc('SDL_PollEvent', integer, [ptr])
        self.delay = proc('SDL_Delay', None, [C.c_uint32])
        self.texture = proc('SDL_CreateTexture', ptr, [ptr, C.c_uint32, integer, integer, integer])
        self.update_texture = proc('SDL_UpdateTexture', integer, [ptr, ptr, ptr, integer])
        self.texture_blend = proc('SDL_SetTextureBlendMode', integer, [ptr, integer])
        self.texture_color = proc('SDL_SetTextureColorMod', integer, [ptr, C.c_uint8, C.c_uint8, C.c_uint8])
        self.copy = proc('SDL_RenderCopy', integer, [ptr, ptr, C.POINTER(Rect), C.POINTER(Rect)])
        self.destroy_texture = proc('SDL_DestroyTexture', None, [ptr])
        self.destroy_renderer = proc('SDL_DestroyRenderer', None, [ptr])
        self.destroywin = proc('SDL_DestroyWindow', None, [ptr])
        self.num_joysticks = proc('SDL_NumJoysticks', integer, [])
        self.is_controller = proc('SDL_IsGameController', integer, [integer])
        self.open_controller = proc('SDL_GameControllerOpen', ptr, [integer])
        self.open_joystick = proc('SDL_JoystickOpen', ptr, [integer])
        self.close_controller = proc('SDL_GameControllerClose', None, [ptr])
        self.close_joystick = proc('SDL_JoystickClose', None, [ptr])
        self.controller_event_state = proc('SDL_GameControllerEventState', integer, [integer])
        self.joystick_event_state = proc('SDL_JoystickEventState', integer, [integer])
        self.controller_joystick = proc('SDL_GameControllerGetJoystick', ptr, [ptr])
        self.joystick_id = proc('SDL_JoystickInstanceID', integer, [ptr])
        self.geterr = proc('SDL_GetError', C.c_char_p, [])
        if self.init(0x20 | 0x200 | 0x2000) != 0:
            raise RuntimeError(self.geterr().decode())
        self.controllers, self.joysticks, self.controller_ids, self.input_indices = [], [], set(), set()
        self.controller_event_state(1); self.joystick_event_state(1); self.open_inputs()
        flags = 0x00000004 if os.environ.get('R36S_WINDOWED') else 0x00001001
        self.win = self.createwin(b'R36S ESP-32 Flasher', 0x2FFF0000, 0x2FFF0000, W, H, flags)
        if not self.win:
            raise RuntimeError(self.geterr().decode())
        self.r = self.renderer(self.win, -1, 0x02 | 0x04) or self.renderer(self.win, -1, 0)
        if not self.r:
            raise RuntimeError(self.geterr().decode())
        self.logical(self.r, W, H)
        pixels = bytearray((ROOT / 'assets' / 'font.rgba').read_bytes())
        for gy in range(6):
            for gx in range(16):
                bx, by = gx * 8, gy * 12
                for yy in range(12):
                    for xx in range(6, -1, -1):
                        src = ((by + yy) * 128 + bx + xx) * 4
                        if pixels[src + 3] and pixels[src + 7] < pixels[src + 3]:
                            pixels[src + 4:src + 8] = pixels[src:src + 4]
        self.font = self.texture(self.r, 0x16762004, 0, 128, 72)
        data = C.create_string_buffer(bytes(pixels))
        self.update_texture(self.font, None, C.cast(data, ptr), 128 * 4)
        self.texture_blend(self.font, 1)

    def open_inputs(self):
        for index in range(self.num_joysticks()):
            if index in self.input_indices:
                continue
            if self.is_controller(index):
                handle = self.open_controller(index)
                if handle:
                    self.controllers.append(handle)
                    joy = self.controller_joystick(handle)
                    if joy:
                        self.controller_ids.add(self.joystick_id(joy))
                    self.input_indices.add(index)
                    continue
            handle = self.open_joystick(index)
            if handle:
                self.joysticks.append(handle); self.input_indices.add(index)

    def set_color(self, color):
        rgb = COLORS[color] if isinstance(color, str) else color
        self.color(self.r, *rgb, 255)

    def rect(self, x, y, w, h, color, border=None):
        r = Rect(int(x), int(y), max(1, int(w)), max(1, int(h)))
        self.set_color(color); self.fill(self.r, C.byref(r))
        if border:
            self.set_color(border); self.draw(self.r, C.byref(r))

    def text(self, x, y, value, color='ink', scale=1.0, max_chars=None):
        if isinstance(color, str):
            color = COLORS[color]
        self.texture_color(self.font, *color)
        value = str(value).encode('ascii', 'replace').decode('ascii')
        if max_chars is not None:
            value = shorten(value, max_chars)
        for i, char in enumerate(value):
            code = ord(char)
            if code < 32 or code > 127:
                continue
            sx, sy = ((code - 32) % 16) * 8, ((code - 32) // 16) * 12
            src = Rect(sx, sy, 8, 12)
            dst = Rect(int(x + i * 8 * scale), int(y), int(8 * scale), int(12 * scale))
            self.copy(self.r, self.font, C.byref(src), C.byref(dst))

    def finish(self):
        self.present(self.r)

    def close(self):
        for handle in self.controllers:
            self.close_controller(handle)
        for handle in self.joysticks:
            self.close_joystick(handle)
        self.destroy_texture(self.font); self.destroy_renderer(self.r); self.destroywin(self.win); self.quit()


class App:
    def __init__(self, canvas):
        self.g = canvas
        self.items = list_firmware()
        self.index = 0
        self.scroll = 0
        self.port_index = 0
        self.notice = 'READY  |  COPY .BIN TO /BOOT/ESP32-FIRMWARE'
        self.notice_color = 'green'
        self.busy = False
        self.running = True
        self.load_catalog = catalog()
        self.confirm_path = None
        self.confirm_deadline = 0
        self.flash_dialog = False
        self.flash_done = False
        self.menu_open = False
        self.menu_index = 0
        self.flash_phase = 'READY'
        self.flash_percent = 0
        self.flash_target = ''
        self.flash_result_color = 'blue2'
        self.flash_logs = []
        self.flash_lock = threading.Lock()
        self.section = 'FIRMWARE'
        self.serial_logs = []
        self.serial_lock = threading.Lock()
        self.serial_stop = threading.Event()
        self.serial_thread = None
        self.serial_status = 'NOT CONNECTED'
        self.serial_log_scroll = 0

    def ports(self):
        return serial_ports()

    def selected_port(self):
        ports = self.ports()
        if not ports:
            return ''
        self.port_index %= len(ports)
        return ports[self.port_index]

    def selected(self):
        return self.items[self.index] if self.items else None

    def message(self, text, color='blue'):
        self.notice = str(text).upper()
        self.notice_color = color

    def add_flash_log(self, line):
        line = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', str(line))
        line = ''.join(char for char in line if char == '\t' or 32 <= ord(char) < 127).strip()
        if not line:
            return
        with self.flash_lock:
            self.flash_logs.append(shorten(line, 72))
            self.flash_logs = self.flash_logs[-10:]

    def add_serial_log(self, line):
        line = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', str(line))
        line = ''.join(char for char in line if char == '\t' or 32 <= ord(char) < 127).strip()
        if not line:
            return
        stamp = time.strftime('%H:%M:%S')
        with self.serial_lock:
            self.serial_logs.append(f'{stamp} {line}')
            self.serial_logs = self.serial_logs[-300:]
            self.serial_log_scroll = 0

    def stop_serial_monitor(self, status='STOPPED'):
        self.serial_stop.set()
        if self.serial_thread and self.serial_thread.is_alive():
            self.serial_status = 'STOPPING'
        else:
            self.serial_status = status

    def start_serial_monitor(self):
        if self.busy:
            self.message('WAIT FOR FLASH TO FINISH BEFORE OPENING LOGS', 'amber')
            return
        if self.serial_thread and self.serial_thread.is_alive():
            self.stop_serial_monitor()
            return
        port = self.selected_port()
        if not port:
            self.serial_status = 'NO USB SERIAL DEVICE'
            self.add_serial_log('Connect the ESP32 through the R36S OTG adapter, then press A.')
            return
        if not os.access(port, os.R_OK | os.W_OK):
            self.serial_status = 'SERIAL ACCESS DENIED'
            self.add_serial_log('Serial access denied. Run the installer and reconnect the ESP32.')
            return
        self.serial_stop.clear()
        self.serial_status = 'CONNECTING'
        self.add_serial_log(f'Opening {port_name(port)} at 115200 baud.')
        self.serial_thread = threading.Thread(target=self.serial_worker, args=(port,), daemon=True)
        self.serial_thread.start()

    def serial_worker(self, port):
        try:
            sys.path.insert(0, str(ROOT / 'engine' / 'vendor'))
            import serial
            with serial.Serial(port, 115200, timeout=0.25, write_timeout=0.25) as connection:
                try:
                    connection.dtr = False
                    connection.rts = False
                except (OSError, serial.SerialException):
                    pass
                self.serial_status = 'LISTENING 115200'
                self.add_serial_log('Serial console connected. Reset the ESP32 to capture its boot messages.')
                pending = bytearray()
                while not self.serial_stop.is_set():
                    chunk = connection.read(256)
                    if not chunk:
                        continue
                    for byte in chunk:
                        if byte in (10, 13):
                            if pending:
                                self.add_serial_log(pending.decode('utf-8', 'replace'))
                                pending.clear()
                        elif byte == 8:
                            if pending:
                                pending.pop()
                        elif byte >= 32 or byte == 9:
                            pending.append(byte)
                            if len(pending) >= 160:
                                self.add_serial_log(pending.decode('utf-8', 'replace'))
                                pending.clear()
                if pending:
                    self.add_serial_log(pending.decode('utf-8', 'replace'))
            self.serial_status = 'STOPPED'
            self.add_serial_log('Serial console disconnected.')
        except Exception as error:
            self.serial_status = 'SERIAL ERROR'
            self.add_serial_log(f'Serial console error: {error}')
        finally:
            self.serial_stop.clear()

    def run_flash_command(self, args, phase, low, high, timeout):
        self.flash_phase = phase
        self.flash_percent = low
        self.add_flash_log(phase)
        output = []
        try:
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    bufsize=0)
        except OSError as error:
            self.add_flash_log('ERROR: ' + str(error))
            return 127, str(error)

        def read_output():
            line = bytearray()

            def emit():
                if not line:
                    return
                text = bytes(line).decode('utf-8', 'replace')
                line.clear()
                output.append(text)
                self.add_flash_log(text)
                for match in re.finditer(r'(\d{1,3})\s*%', text):
                    part = min(100, int(match.group(1)))
                    self.flash_percent = max(self.flash_percent, low + (high - low) * part // 100)

            try:
                while True:
                    chunk = os.read(proc.stdout.fileno(), 256)
                    if not chunk:
                        break
                    for byte in chunk:
                        if byte in (10, 13, 8):
                            emit()
                        else:
                            line.append(byte)
                emit()
            except OSError as error:
                self.add_flash_log('LOG READ: ' + str(error))

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            reader.join(timeout=2)
            self.add_flash_log('COMMAND TIMED OUT')
            return 124, '\n'.join(output) + '\nCOMMAND TIMED OUT'
        reader.join(timeout=3)
        if code == 0:
            self.flash_percent = high
            self.add_flash_log(phase + ' COMPLETE')
        else:
            self.add_flash_log(phase + ' FAILED')
        return code, '\n'.join(output)

    def refresh(self):
        current = str(self.selected()) if self.selected() else ''
        self.items = list_firmware()
        self.index = next((i for i, item in enumerate(self.items) if str(item) == current), 0)
        self.scroll = min(self.scroll, max(0, len(self.items) - 5))
        self.message(f'{len(self.items)} FILES READY  |  FIRMWARE LIST UPDATED', 'green')

    def move(self, step):
        if not self.items:
            return
        self.index = max(0, min(len(self.items) - 1, self.index + step))
        if self.index < self.scroll:
            self.scroll = self.index
        if self.index >= self.scroll + 5:
            self.scroll = self.index - 4

    def activate(self):
        if self.busy:
            return
        path = self.selected()
        if not path:
            self.message('NO FIRMWARE FILES FOUND', 'red')
            return
        if path.suffix.lower() == '.bin':
            meta = self.load_catalog.get(path.name, {})
            if meta.get('mode') == 'full':
                if self.confirm_path == str(path) and time.monotonic() <= self.confirm_deadline:
                    self.confirm_path = None
                    self.confirm_deadline = 0
                    self.start_flash(path, full_confirmed=True)
                else:
                    self.confirm_path = str(path)
                    self.confirm_deadline = time.monotonic() + 8
                    self.message('ERASES ESP32 FLASH  |  PRESS A AGAIN TO CONFIRM', 'red')
            else:
                self.confirm_path = None
                self.start_flash(path)
        else:
            self.message('CHOOSE A .BIN FILE', 'red')

    def start_flash(self, path, full_confirmed=False):
        if self.serial_thread and self.serial_thread.is_alive():
            self.stop_serial_monitor('FLASHING')
            self.serial_thread.join(timeout=1)
            if self.serial_thread.is_alive():
                self.message('CLOSE SERIAL LOGS BEFORE FLASHING', 'amber')
                return
        port = self.selected_port()
        tool = esptool_path()
        if not port:
            self.message('CONNECT ESP32 TO THE OTG USB PORT', 'red')
            return
        if not os.access(port, os.R_OK | os.W_OK):
            self.message('SERIAL ACCESS DENIED  |  RUN INSTALLER, RECONNECT USB', 'red')
            return
        if not tool:
            self.message('ESPTOOL MISSING FROM THIS INSTALL', 'red')
            return
        meta = self.load_catalog.get(path.name, {})
        if meta.get('mode') == 'full' and not full_confirmed:
            self.message('PRESS A AGAIN TO CONFIRM FULL ERASE', 'red')
            return
        self.busy = True
        self.flash_dialog = True
        self.flash_done = False
        self.flash_phase = 'STARTING'
        self.flash_percent = 1
        self.flash_result_color = 'blue2'
        self.flash_target = meta.get('title', path.name)
        with self.flash_lock:
            self.flash_logs = []
        self.message('FLASH STARTED  |  KEEP USB CONNECTED', 'blue')
        self.add_flash_log('TARGET: ' + self.flash_target)
        self.add_flash_log('PORT: ' + port_name(port))
        self.add_flash_log('BAUD: 115200')
        threading.Thread(target=self.flash_worker, args=(tool, port, path, full_confirmed), daemon=True).start()

    def flash_worker(self, tool, port, path, full_confirmed=False):
        global NOTICE
        try:
            self.flash_phase = 'CHECKING IMAGE'
            self.flash_percent = 3
            self.add_flash_log('CHECKING IMAGE HEADER AND CHECKSUM')
            with path.open('rb') as image_file:
                header = image_file.read(16)
            if len(header) < 16 or header[0] != 0xE9:
                self.message('NOT AN APP-ONLY ESP32 IMAGE  |  MERGED FILES NOT SUPPORTED', 'red')
                return
            chip_id = struct.unpack_from('<H', header, 12)[0]
            if chip_id not in (0, 0xFFFF):
                self.message(f'WRONG CHIP IMAGE  |  ESP32 CHIP ID IS {chip_id}', 'red')
                return
            image_hash = sha256_file(path)
            is_micropython = image_hash == 'e67ad6015a0a504c1fec9aa9bbf589d0432ed28e62546f4f8dd8a147f8bd95f6'
            meta = self.load_catalog.get(path.name, {})
            if not is_micropython and meta.get('mode') == 'full':
                self.message('UNRECOGNIZED FULL-FLASH IMAGE  |  FLASH STOPPED', 'red')
                return
            if is_micropython:
                if not full_confirmed or meta.get('mode') != 'full':
                    self.message('FULL ERASE NEEDS A SECOND A PRESS', 'red')
                    return
                flash_bytes = connected_flash_bytes(tool, port)
                if flash_bytes is None:
                    self.message(NOTICE or 'CANNOT IDENTIFY ESP32 FLASH SIZE', 'red')
                    return
                if flash_bytes < 4 * 1024 * 1024:
                    self.message('MICROPYTHON NEEDS AT LEAST 4 MB FLASH', 'red')
                    return
                if path.stat().st_size + 0x1000 > flash_bytes:
                    self.message('IMAGE IS LARGER THAN CONNECTED ESP32 FLASH', 'red')
                    return
                self.add_flash_log(f'FLASH CHIP: {flash_bytes // (1024 * 1024)} MB')
                erase_code, erase_output = self.run_flash_command(
                    [tool, '--chip', 'esp32', '--port', port, '--baud', '115200', 'erase_flash'],
                    'ERASING ESP32', 5, 18, 300)
                if erase_code:
                    self.message('ERASE FAILED  |  ' + shorten(erase_output, 48), 'red')
                    return
                write_code, write_output = self.run_flash_command(
                    [tool, '--chip', 'esp32', '--port', port, '--baud', '115200',
                     'write_flash', '0x1000', str(path)], 'WRITING MICROPYTHON', 18, 86, 900)
                if write_code:
                    self.message('FLASH FAILED  |  ' + shorten(write_output, 52), 'red')
                    return
                verify_code, verify_output = self.run_flash_command(
                    [tool, '--chip', 'esp32', '--port', port, '--baud', '115200',
                     'verify_flash', '0x1000', str(path)], 'VERIFYING MICROPYTHON', 86, 100, 900)
                if verify_code == 0:
                    self.message('MICROPYTHON 1.29.0  |  FLASH VERIFIED', 'green')
                else:
                    self.message('WRITTEN, VERIFY FAILED  |  ' + shorten(verify_output, 45), 'red')
                return
            if path.name.lower().startswith('micropython'):
                self.message('USE THE INCLUDED FULL-ERASE MICROPYTHON IMAGE', 'red')
                return
            self.flash_phase = 'READING PARTITION TABLE'
            self.flash_percent = 8
            self.add_flash_log('READING PARTITION TABLE')
            entries = read_partitions(tool, port)
            if entries is None:
                self.message(NOTICE or 'CANNOT READ ESP32 PARTITION TABLE', 'red')
                return
            offset = 0x10000
            app = next((entry for entry in entries if entry[0] == 0 and entry[2] == offset), None)
            if app is None:
                self.message(f'NO APP PARTITION AT {offset:#x}', 'red')
                return
            capacity = app[3]
            size = path.stat().st_size
            self.add_flash_log(f'APP SLOT: {capacity:,} BYTES  |  IMAGE: {size:,} BYTES')
            if size > capacity:
                self.message(f'IMAGE TOO LARGE  |  {size:,} BYTES > {capacity:,} APP BYTES', 'red')
                return
            write_code, write_output = self.run_flash_command(
                [tool, '--chip', 'esp32', '--port', port, '--baud', '115200',
                 'write_flash', hex(offset), str(path)], 'WRITING APP', 12, 84, 600)
            if write_code:
                self.message('FLASH FAILED  |  ' + shorten(write_output, 52), 'red')
                return
            verify_code, verify_output = self.run_flash_command(
                [tool, '--chip', 'esp32', '--port', port, '--baud', '115200',
                 'verify_flash', hex(offset), str(path)], 'VERIFYING APP', 84, 100, 600)
            if verify_code == 0:
                self.message(path.name + '  |  FLASH VERIFIED', 'green')
            else:
                self.message('WRITTEN, VERIFY FAILED  |  ' + shorten(verify_output, 45), 'red')
        except subprocess.TimeoutExpired:
            self.message('FLASH OR VERIFY TIMED OUT AT 115200 BAUD', 'red')
        except OSError as error:
            self.message('FLASH ERROR  |  ' + shorten(error, 52), 'red')
        except Exception as error:
            self.message('FLASH ERROR  |  ' + shorten(error, 52), 'red')
        finally:
            self.flash_done = True
            self.flash_phase = 'COMPLETE' if 'VERIFIED' in self.notice else 'STOPPED'
            if 'VERIFIED' in self.notice:
                self.flash_percent = 100
                self.flash_result_color = 'green'
            else:
                self.flash_result_color = 'red'
            self.add_flash_log(self.notice)
            self.busy = False

    def draw(self):
        g = self.g
        g.set_color('bg'); g.clear(g.r)
        if self.section == 'LOGS':
            self.draw_logs()
            g.finish()
            return
        port = self.selected_port()
        status = 'USB READY' if port and os.access(port, os.R_OK | os.W_OK) else ('USB ACCESS' if port else 'USB EMPTY')
        g.rect(0, 0, 193, H, 'panel', 'line')
        g.rect(8, 8, 177, 59, 'blue')
        g.text(18, 21, 'R36S', 'white', 1.55)
        g.text(18, 44, 'ESP-32 FLASHER', 'white', 1.25)
        g.rect(8, 76, 177, 42, 'white', 'line')
        g.rect(15, 92, 10, 10, 'green' if status == 'USB READY' else 'amber' if port else 'red')
        g.text(34, 88, status, 'green' if status == 'USB READY' else 'amber' if port else 'red', 1.2, 17)
        g.rect(8, 126, 177, 31, 'blue2')
        g.text(18, 132, 'FIRMWARE', 'white', 1.25)
        for row in range(5):
            i = self.scroll + row
            y = 163 + row * 50
            if i >= len(self.items):
                break
            path = self.items[i]
            active = i == self.index
            g.rect(12, y, 169, 46, 'select' if active else ('white' if row % 2 == 0 else 'panel'),
                   'blue2' if active else 'grid')
            g.rect(12, y + 1, 6, 44, 'green')
            meta = self.load_catalog.get(path.name, {})
            title = meta.get('list_title', meta.get('title', path.stem.replace('_', ' ')))
            g.text(24, y + 2, shorten(title.upper(), 15), 'blue' if active else 'ink', 1.18)
            try:
                size = path.stat().st_size
                detail = 'FULL ERASE' if meta.get('mode') == 'full' else f'{size / 1048576:.2f} MB'
                g.text(24, y + 26, detail, 'red' if meta.get('mode') == 'full' else 'muted', 1.13)
            except OSError:
                pass
        if not self.items:
            g.text(19, 170, 'NO FIRMWARE', 'red', 1.2)
            g.text(19, 199, 'COPY BIN TO', 'muted', 1.1)
            g.text(19, 222, '/BOOT/ESP32-FIRMWARE', 'blue', 0.95)
        g.rect(12, 420, 169, 43, 'white', 'line')
        g.text(20, 424, f'{len(self.items)} FILES', 'green', 1.15)
        g.text(20, 445, 'X  RESCAN', 'blue', 1.1)

        g.rect(201, 8, 431, 423, 'panel', 'line')
        g.rect(201, 8, 431, 38, 'blue2')
        path = self.selected()
        g.text(216, 22, 'FIRMWARE DETAILS', 'white', 1.25)
        if path:
            meta = self.load_catalog.get(path.name, {})
            is_full = meta.get('mode') == 'full'
            g.text(218, 58, shorten(meta.get('title', path.stem.replace('_', ' ')).upper(), 29), 'blue', 1.55)
            g.rect(218, 86, 396, 2, 'blue2')
            g.text(218, 103, 'BOARD', 'muted', 1.15); g.text(303, 101, 'CLASSIC ESP32', 'ink', 1.2)
            g.text(218, 135, 'IMAGE', 'muted', 1.15)
            try:
                size = path.stat().st_size
                g.text(303, 133, f'{size / 1048576:.2f} MB', 'ink', 1.2)
            except OSError:
                g.text(303, 133, 'FILE MISSING', 'red', 1.15)
            g.text(218, 170, 'ABOUT', 'muted', 1.15)
            desc = meta.get('description', 'ESP32 firmware image.')
            for i, line in enumerate([shorten(desc[j:j + 41], 41) for j in range(0, min(len(desc), 82), 41)]):
                g.text(218, 195 + i * 23, line.upper(), 'ink', 1.12, 41)
            if is_full:
                g.rect(218, 274, 396, 94, 'red', 'line')
                g.text(230, 282, 'A  ERASE + INSTALL', 'white', 1.45)
                g.text(230, 313, 'PRESS A AGAIN TO CONFIRM', 'white', 1.15)
                g.text(230, 340, 'REPLACES CURRENT ESP32 DATA', 'white', 1.1)
                g.text(218, 380, 'CLASSIC ESP32  |  MINIMUM 4 MB', 'red', 1.12)
            else:
                g.rect(218, 274, 396, 82, 'greenbg', 'line')
                g.text(230, 283, 'A  FLASH + VERIFY', 'green', 1.45)
                g.text(230, 315, 'APP ONLY  |  115200 BAUD', 'ink', 1.18)
                g.text(218, 370, 'BOOTLOADER AND SETTINGS STAY', 'muted', 1.08)
        else:
            g.text(226, 110, 'NO FIRMWARE SELECTED', 'blue', 1.45)
            g.text(226, 158, 'COPY BIN FILES TO:', 'ink', 1.25)
            g.rect(218, 195, 396, 49, 'select', 'line')
            g.text(230, 210, '/BOOT/ESP32-FIRMWARE/', 'blue', 1.2)
            g.text(226, 278, 'A  FLASHES AND VERIFIES', 'green', 1.2)
            g.text(226, 319, 'X  RESCANS THE CARD', 'muted', 1.2)

        g.rect(8, 436, 624, 43, 'white', 'line')
        color = COLORS.get(self.notice_color, COLORS['blue'])
        g.text(16, 439, self.notice, color, 1.0, 68)
        g.text(16, 462, 'UP/DOWN FILES   A FLASH   Y LOGS   START MENU', 'blue', 1.0, 74)
        if self.flash_dialog:
            self.draw_flash_dialog()
        elif self.menu_open:
            self.draw_exit_menu()
        g.finish()

    def draw_logs(self):
        g = self.g
        port = self.selected_port()
        listening = bool(self.serial_thread and self.serial_thread.is_alive() and not self.serial_stop.is_set())
        status = self.serial_status
        g.rect(10, 8, 620, 39, 'blue')
        g.text(24, 20, 'ESP32 SERIAL LOGS', 'white', 1.5)
        g.rect(10, 55, 620, 42, 'white', 'line')
        g.rect(18, 70, 10, 10, 'green' if listening else 'amber' if port else 'red')
        g.text(38, 66, status, 'green' if listening else 'amber' if port else 'red', 1.15, 35)
        g.text(362, 66, shorten(port_name(port) if port else 'NO USB DEVICE', 31), 'blue', 1.05, 31)
        g.rect(10, 104, 620, 326, 'black', 'line')
        with self.serial_lock:
            logs = list(self.serial_logs)
        rows = 13
        end = max(0, len(logs) - self.serial_log_scroll)
        start = max(0, end - rows)
        visible = logs[start:end]
        if not visible:
            visible = ['Connect an ESP32, then press A to listen at 115200 baud.',
                       'After connecting, reset the ESP32 to capture its boot output.',
                       'Some firmware sends no readable serial text.']
        for index, line in enumerate(visible[-rows:]):
            g.text(20, 115 + index * 23, shorten(line, 72), 'green', 1.05, 72)
        g.rect(10, 438, 620, 41, 'white', 'line')
        listen_action = 'A STOP LOGS' if listening else 'A START LOGS'
        g.text(18, 443, f'{listen_action}   X CLEAR   UP/DOWN SCROLL   B BACK', 'blue', 0.96, 75)
        g.text(18, 462, 'L/R PORT   Y FIRMWARE   START MENU', 'blue', 0.98, 61)

    def draw_exit_menu(self):
        g = self.g
        g.rect(0, 0, W, H, 'bg')
        g.rect(30, 70, 580, 340, 'white', 'blue')
        g.rect(38, 78, 564, 54, 'blue')
        g.text(58, 95, 'OPTIONS', 'white', 1.65)
        choices = ('EXIT TO EMULATIONSTATION', 'RETURN TO FLASHER')
        for index, label in enumerate(choices):
            y = 160 + index * 72
            active = index == self.menu_index
            g.rect(58, y, 524, 58, 'select' if active else 'panel', 'blue2' if active else 'line')
            g.text(76, y + 17, label, 'blue' if active else 'ink', 1.35)
        g.text(58, 326, 'UP/DOWN CHOOSE   A SELECT   B BACK', 'blue', 1.12)

    def draw_flash_dialog(self):
        g = self.g
        g.rect(0, 0, W, H, 'bg')
        g.rect(20, 18, 600, 444, 'white', 'blue')
        g.rect(28, 26, 584, 47, 'blue')
        g.text(42, 39, 'FLASH: ' + shorten(self.flash_target, 48), 'white', 1.25, 52)
        g.text(42, 87, self.flash_phase, 'blue', 1.25, 55)
        g.rect(42, 116, 556, 32, 'white', 'blue2')
        percent = max(0, min(100, self.flash_percent))
        fill = max(0, int(548 * percent / 100))
        if fill:
            g.rect(46, 120, fill, 24, self.flash_result_color if self.flash_done else 'blue2')
        g.text(548, 124, f'{percent:3d}%', 'ink' if percent < 17 else 'white', 1.12)
        g.text(42, 164, 'FLASH LOG', 'blue', 1.22)
        g.rect(42, 188, 556, 206, 'black', 'line')
        with self.flash_lock:
            logs = list(self.flash_logs[-9:])
        for i, line in enumerate(logs):
            g.text(52, 198 + i * 21, shorten(line, 58),
                   'red' if self.flash_done and self.flash_result_color == 'red' else 'green', 1.08, 58)
        g.rect(42, 407, 556, 39, 'greenbg' if self.flash_done and self.flash_result_color == 'green' else 'white', 'line')
        footer = 'A / B CLOSE' if self.flash_done else 'KEEP ESP32 CONNECTED  |  DO NOT EXIT'
        footer_color = 'green' if self.flash_done and self.flash_result_color == 'green' else 'red' if self.flash_done else 'blue'
        g.text(54, 418, footer, footer_color, 1.18, 52)

    def key(self, key):
        if self.flash_dialog:
            if self.flash_done and key in ('a', 'b', 'escape', 'x', 'start'):
                self.flash_dialog = False
            return
        if self.busy:
            return
        if key == 'y':
            if self.section == 'LOGS':
                self.stop_serial_monitor()
            self.section = 'LOGS' if self.section == 'FIRMWARE' else 'FIRMWARE'
            return
        if self.section == 'LOGS':
            if key == 'a':
                self.start_serial_monitor()
            elif key == 'x':
                with self.serial_lock:
                    self.serial_logs.clear()
                    self.serial_log_scroll = 0
                self.serial_status = 'CLEARED'
            elif key == 'up':
                with self.serial_lock:
                    self.serial_log_scroll = min(max(0, len(self.serial_logs) - 1), self.serial_log_scroll + 1)
            elif key == 'down':
                self.serial_log_scroll = max(0, self.serial_log_scroll - 1)
            elif key in ('l', 'r'):
                self.stop_serial_monitor()
                ports = self.ports()
                if ports:
                    self.port_index = (self.port_index + (-1 if key == 'l' else 1)) % len(ports)
            elif key in ('b', 'escape', 'left'):
                self.stop_serial_monitor()
                self.section = 'FIRMWARE'
            elif key == 'start':
                self.stop_serial_monitor()
                self.menu_index = 0
                self.menu_open = True
            return
        if self.menu_open:
            if key in ('up', 'down'):
                self.menu_index = 1 - self.menu_index
            elif key == 'a':
                if self.menu_index == 0:
                    self.running = False
                else:
                    self.menu_open = False
            elif key in ('b', 'escape', 'start', 'left'):
                self.menu_open = False
            return
        if key in ('up', 'down'):
            self.confirm_path = None
            self.move(-1 if key == 'up' else 1)
        elif key == 'a':
            self.activate()
        elif key in ('x', 's'):
            self.refresh()
        elif key in ('l', 'r'):
            ports = self.ports()
            if ports:
                self.confirm_path = None
                self.port_index = (self.port_index + (-1 if key == 'l' else 1)) % len(ports)
                self.message('USB PORT: ' + port_name(self.selected_port()), 'blue')
            else:
                self.message('CONNECT ESP32 TO OTG USB', 'amber')
        elif key in ('start', 'b', 'escape'):
            self.menu_index = 0
            self.menu_open = True

    def run(self):
        event = C.create_string_buffer(128)
        last_draw = 0
        axis_time = 0
        while self.running:
            while self.g.event(event):
                typ = struct.unpack_from('I', event.raw, 0)[0]
                if typ == 0x100:
                    self.running = False
                    break
                if typ in (0x605, 0x653):
                    self.g.open_inputs()
                if typ == 0x300:
                    code = struct.unpack_from('i', event.raw, 16)[0]
                    keys = {79: 'right', 80: 'left', 81: 'down', 82: 'up', 40: 'a', 41: 'escape',
                            4: 'a', 5: 'b', 27: 'x', 22: 's', 28: 'y'}
                    if code in keys and not event.raw[13]:
                        self.key(keys[code])
                if typ == 0x651:
                    button = event.raw[12]
                    key = {0: 'b', 1: 'a', 2: 'x', 3: 'y', 4: 'escape', 6: 'start',
                           9: 'l', 10: 'r', 11: 'up', 12: 'down', 13: 'left', 14: 'right'}.get(button)
                    if key:
                        self.key(key)
                which = struct.unpack_from('i', event.raw, 8)[0]
                raw_pad = which not in self.g.controller_ids
                if typ == 0x603 and raw_pad:
                    button = event.raw[12]
                    key = {0: 'b', 1: 'a', 2: 'x', 3: 'y', 4: 'l', 5: 'r', 6: 'start', 7: 'start',
                           8: 'up', 9: 'down', 10: 'left', 11: 'right', 13: 'b'}.get(button)
                    if key:
                        self.key(key)
                if typ == 0x602 and raw_pad:
                    hat = event.raw[13]
                    if hat & 0x01: self.key('up')
                    if hat & 0x02: self.key('right')
                    if hat & 0x04: self.key('down')
                    if hat & 0x08: self.key('left')
                if typ in (0x600, 0x650):
                    axis = event.raw[12]; value = struct.unpack_from('h', event.raw, 16)[0]
                    if axis in (0, 1) and abs(value) > 22000 and time.monotonic() - axis_time > .23:
                        axis_time = time.monotonic()
                        self.key(('left' if value < 0 else 'right') if axis == 0 else ('up' if value < 0 else 'down'))
            if time.monotonic() - last_draw > .12:
                self.draw(); last_draw = time.monotonic()
            self.g.delay(18)
        self.stop_serial_monitor()
        if self.serial_thread and self.serial_thread.is_alive():
            self.serial_thread.join(timeout=1)
        self.g.close()


if __name__ == '__main__':
    try:
        App(Canvas()).run()
    except Exception as error:
        print('R36S ESP-32 Flasher error:', repr(error), file=sys.stderr)
        raise
