import os
import threading
from dataclasses import dataclass
import selectors
import string

from evdev import UInput, ecodes as e, util, InputDevice, list_devices, KeyEvent

from plover.output.keyboard import GenericKeyboardEmulation
from plover.machine.keyboard_capture import Capture
from plover.key_combo import parse_key_combo
from plover import log

@dataclass
class KeyCodeInfo:
    keycode: int
    is_shifted: bool
# Tuple is (keycode, is_shifted)
BASE_LAYOUT: dict[str, KeyCodeInfo] = {
    # Modifiers
    "alt_l": e.KEY_LEFTALT,
    "alt_r": e.KEY_RIGHTALT,
    "alt": e.KEY_LEFTALT,
    "ctrl_l": e.KEY_LEFTCTRL,
    "ctrl_r": e.KEY_RIGHTCTRL,
    "ctrl": e.KEY_LEFTCTRL,
    "control_l": e.KEY_LEFTCTRL,
    "control_r": e.KEY_RIGHTCTRL,
    "control": e.KEY_LEFTCTRL,
    "shift_l": e.KEY_LEFTSHIFT,
    "shift_r": e.KEY_RIGHTSHIFT,
    "shift": e.KEY_LEFTSHIFT,
    "super_l": e.KEY_LEFTMETA,
    "super_r": e.KEY_RIGHTMETA,
    "super": e.KEY_LEFTMETA,
    # Numbers
    "1": e.KEY_1,
    "2": e.KEY_2,
    "3": e.KEY_3,
    "4": e.KEY_4,
    "5": e.KEY_5,
    "6": e.KEY_6,
    "7": e.KEY_7,
    "8": e.KEY_8,
    "9": e.KEY_9,
    "0": e.KEY_0,
    # Symbols
    " ": KeyCodeInfo(keycode=e.KEY_SPACE, is_shifted=False),
    "\b": KeyCodeInfo(keycode=e.KEY_BACKSPACE, is_shifted=False),
    "\n": KeyCodeInfo(keycode=e.KEY_ENTER, is_shifted=False),
    # https://github.com/openstenoproject/plover/blob/9b5a357f1fb57cb0a9a8596ae12cd1e84fcff6c4/plover/oslayer/osx/keyboardcontrol.py#L75
    # https://gist.github.com/jfortin42/68a1fcbf7738a1819eb4b2eef298f4f8
    "return": KeyCodeInfo(keycode=e.KEY_ENTER, is_shifted=False),
    "tab": KeyCodeInfo(keycode=e.KEY_TAB, is_shifted=False),
    "backspace": KeyCodeInfo(keycode=e.KEY_BACKSPACE, is_shifted=False),
    "delete": KeyCodeInfo(keycode=e.KEY_DELETE, is_shifted=False),
    "escape": KeyCodeInfo(keycode=e.KEY_ESC, is_shifted=False),
    "clear": KeyCodeInfo(keycode=e.KEY_CLEAR, is_shifted=False),
    # Navigation
    "up": KeyCodeInfo(keycode=e.KEY_UP, is_shifted=False),
    "down": KeyCodeInfo(keycode=e.KEY_DOWN, is_shifted=False),
    "left": KeyCodeInfo(keycode=e.KEY_LEFT, is_shifted=False),
    "right": KeyCodeInfo(keycode=e.KEY_RIGHT, is_shifted=False),
    "page_up": KeyCodeInfo(keycode=e.KEY_PAGEUP, is_shifted=False),
    "page_down": KeyCodeInfo(keycode=e.KEY_PAGEDOWN, is_shifted=False),
    "home": KeyCodeInfo(keycode=e.KEY_HOME, is_shifted=False),
    "insert": KeyCodeInfo(keycode=e.KEY_INSERT, is_shifted=False),
    "end": KeyCodeInfo(keycode=e.KEY_END, is_shifted=False),
    "space": KeyCodeInfo(keycode=e.KEY_SPACE, is_shifted=False),
    "print": KeyCodeInfo(keycode=e.KEY_PRINT, is_shifted=False),
    # Function keys
    "fn": KeyCodeInfo(keycode=e.KEY_FN, is_shifted=False),
    "f1": KeyCodeInfo(keycode=e.KEY_F1, is_shifted=False),
    "f2": KeyCodeInfo(keycode=e.KEY_F2, is_shifted=False),
    "f3": KeyCodeInfo(keycode=e.KEY_F3, is_shifted=False),
    "f4": KeyCodeInfo(keycode=e.KEY_F4, is_shifted=False),
    "f5": KeyCodeInfo(keycode=e.KEY_F5, is_shifted=False),
    "f6": KeyCodeInfo(keycode=e.KEY_F6, is_shifted=False),
    "f7": KeyCodeInfo(keycode=e.KEY_F7, is_shifted=False),
    "f8": KeyCodeInfo(keycode=e.KEY_F8, is_shifted=False),
    "f9": KeyCodeInfo(keycode=e.KEY_F9, is_shifted=False),
    "f10": KeyCodeInfo(keycode=e.KEY_F10, is_shifted=False),
    "f11": KeyCodeInfo(keycode=e.KEY_F11, is_shifted=False),
    "f12": KeyCodeInfo(keycode=e.KEY_F12, is_shifted=False),
    "f13": KeyCodeInfo(keycode=e.KEY_F13, is_shifted=False),
    "f14": KeyCodeInfo(keycode=e.KEY_F14, is_shifted=False),
    "f15": KeyCodeInfo(keycode=e.KEY_F15, is_shifted=False),
    "f16": KeyCodeInfo(keycode=e.KEY_F16, is_shifted=False),
    "f17": KeyCodeInfo(keycode=e.KEY_F17, is_shifted=False),
    "f18": KeyCodeInfo(keycode=e.KEY_F18, is_shifted=False),
    "f19": KeyCodeInfo(keycode=e.KEY_F19, is_shifted=False),
    "f20": KeyCodeInfo(keycode=e.KEY_F20, is_shifted=False),
    "f21": KeyCodeInfo(keycode=e.KEY_F21, is_shifted=False),
    "f22": KeyCodeInfo(keycode=e.KEY_F22, is_shifted=False),
    "f23": KeyCodeInfo(keycode=e.KEY_F23, is_shifted=False),
    "f24": KeyCodeInfo(keycode=e.KEY_F24, is_shifted=False),
    # Numpad
    "kp_1": KeyCodeInfo(keycode=e.KEY_KP1, is_shifted=False),
    "kp_2": KeyCodeInfo(keycode=e.KEY_KP2, is_shifted=False),
    "kp_3": KeyCodeInfo(keycode=e.KEY_KP3, is_shifted=False),
    "kp_4": KeyCodeInfo(keycode=e.KEY_KP4, is_shifted=False),
    "kp_5": KeyCodeInfo(keycode=e.KEY_KP5, is_shifted=False),
    "kp_6": KeyCodeInfo(keycode=e.KEY_KP6, is_shifted=False),
    "kp_7": KeyCodeInfo(keycode=e.KEY_KP7, is_shifted=False),
    "kp_8": KeyCodeInfo(keycode=e.KEY_KP8, is_shifted=False),
    "kp_9": KeyCodeInfo(keycode=e.KEY_KP9, is_shifted=False),
    "kp_0": KeyCodeInfo(keycode=e.KEY_KP0, is_shifted=False),
    "kp_add": KeyCodeInfo(keycode=e.KEY_KPPLUS, is_shifted=False),
    "kp_decimal": KeyCodeInfo(keycode=e.KEY_KPDOT, is_shifted=False),
    "kp_delete": KeyCodeInfo(keycode=e.KEY_DELETE, is_shifted=False),  # There is no KPDELETE
    "kp_divide": KeyCodeInfo(keycode=e.KEY_KPSLASH, is_shifted=False),
    "kp_enter": KeyCodeInfo(keycode=e.KEY_KPENTER, is_shifted=False),
    "kp_equal": KeyCodeInfo(keycode=e.KEY_KPEQUAL, is_shifted=False),
    "kp_multiply": KeyCodeInfo(keycode=e.KEY_KPASTERISK, is_shifted=False),
    "kp_subtract": KeyCodeInfo(keycode=e.KEY_KPMINUS, is_shifted=False),
    # Media keys
    "audioraisevolume": KeyCodeInfo(keycode=e.KEY_VOLUMEUP, is_shifted=False),
    "audiolowervolume": KeyCodeInfo(keycode=e.KEY_VOLUMEDOWN, is_shifted=False),
    "monbrightnessup": KeyCodeInfo(keycode=e.KEY_BRIGHTNESSUP, is_shifted=False),
    "monbrightnessdown": KeyCodeInfo(keycode=e.KEY_BRIGHTNESSDOWN, is_shifted=False),
    "audiomute": KeyCodeInfo(keycode=e.KEY_MUTE, is_shifted=False),
    "num_lock": KeyCodeInfo(keycode=e.KEY_NUMLOCK, is_shifted=False),
    "eject": KeyCodeInfo(keycode=e.KEY_EJECTCD, is_shifted=False),
    "audiopause": KeyCodeInfo(keycode=e.KEY_PAUSE, is_shifted=False),
    "audionext": KeyCodeInfo(keycode=e.KEY_NEXT, is_shifted=False),
    "audioplay": KeyCodeInfo(keycode=e.KEY_PLAY, is_shifted=False),
    "audiorewind": KeyCodeInfo(keycode=e.KEY_REWIND, is_shifted=False),
    "kbdbrightnessup": KeyCodeInfo(keycode=e.KEY_KBDILLUMUP, is_shifted=False),
    "kbdbrightnessdown": KeyCodeInfo(keycode=e.KEY_KBDILLUMDOWN, is_shifted=False),
}

# Last 5 are "\t\n\r\x0b\x0c" which don't need to be handled
assert all(c in BASE_LAYOUT for c in string.printable[:-5])

MODIFIER_KEY_CODES: set[int] = {
    e.KEY_LEFTSHIFT, e.KEY_RIGHTSHIFT,
    e.KEY_LEFTCTRL, e.KEY_RIGHTCTRL,
    e.KEY_LEFTALT, e.KEY_RIGHTALT,
    e.KEY_LEFTMETA, e.KEY_RIGHTMETA,
}

DEFAULT_LAYOUT = "qwerty"
LAYOUTS = {
    # Only specify keys that differ from qwerty
    "qwerty": {
        **BASE_LAYOUT,
    },
    "qwertz": {
        **BASE_LAYOUT,
        # Top row
        "q": e.KEY_Q,
        "w": e.KEY_W,
        "e": e.KEY_E,
        "r": e.KEY_R,
        "t": e.KEY_T,
        "z": e.KEY_Y,
        "u": e.KEY_U,
        "i": e.KEY_I,
        "o": e.KEY_O,
        "p": e.KEY_P,
        # Middle row
        "a": e.KEY_A,
        "s": e.KEY_S,
        "d": e.KEY_D,
        "f": e.KEY_F,
        "g": e.KEY_G,
        "h": e.KEY_H,
        "j": e.KEY_J,
        "k": e.KEY_K,
        "l": e.KEY_L,
        # Bottom row
        "y": e.KEY_Z,
        "x": e.KEY_X,
        "c": e.KEY_C,
        "v": e.KEY_V,
        "b": e.KEY_B,
        "n": e.KEY_N,
        "m": e.KEY_M,
    },
    "colemak": {
        **BASE_LAYOUT,
        # Top row
        "q": e.KEY_Q,
        "w": e.KEY_W,
        "f": e.KEY_E,
        "p": e.KEY_R,
        "g": e.KEY_T,
        "j": e.KEY_Y,
        "l": e.KEY_U,
        "u": e.KEY_I,
        "y": e.KEY_O,
        # Middle row
        "a": e.KEY_A,
        "r": e.KEY_S,
        "s": e.KEY_D,
        "t": e.KEY_F,
        "d": e.KEY_G,
        "h": e.KEY_H,
        "n": e.KEY_J,
        "e": e.KEY_K,
        "i": e.KEY_L,
        "o": e.KEY_SEMICOLON,
        # Bottom row
        "z": e.KEY_Z,
        "x": e.KEY_X,
        "c": e.KEY_C,
        "v": e.KEY_V,
        "b": e.KEY_B,
        "k": e.KEY_N,
        "m": e.KEY_M,
    },
    "colemak-dh": {
        **BASE_LAYOUT,
        # Top row
        "q": e.KEY_Q,
        "w": e.KEY_W,
        "f": e.KEY_E,
        "p": e.KEY_R,
        "b": e.KEY_T,
        "j": e.KEY_Y,
        "l": e.KEY_U,
        "u": e.KEY_I,
        "y": e.KEY_O,
        # Middle row
        "a": e.KEY_A,
        "r": e.KEY_S,
        "s": e.KEY_D,
        "t": e.KEY_F,
        "g": e.KEY_G,
        "m": e.KEY_H,
        "n": e.KEY_J,
        "e": e.KEY_K,
        "i": e.KEY_L,
        "o": e.KEY_SEMICOLON,
        # Bottom row
        "z": e.KEY_BACKSLASH,  # less than-key
        "x": e.KEY_Z,
        "c": e.KEY_X,
        "d": e.KEY_C,
        "v": e.KEY_V,
        "k": e.KEY_N,
        "h": e.KEY_M,
    },
}

# Ignore shifted keys with `not v[1]`
# us_qwerty = {v[0]: k for k, v in BASE_LAYOUT.items() if not v[1]}
KEYCODE_TO_KEY = {v.keycode: k for k, v in BASE_LAYOUT.items() if not v.is_shifted}

class KeyboardEmulation(GenericKeyboardEmulation):
    def __init__(self):
        super().__init__()
        # Initialize UInput with all keys available
        self._res = util.find_ecodes_by_regex(r"KEY_.*")
        self._ui = UInput(self._res)

    def _update_layout(self, layout):
        if not layout in LAYOUTS:
            log.warning(f"Layout {layout} not supported. Falling back to qwerty.")
        self._KEY_TO_KEYCODEINFO = LAYOUTS.get(layout, LAYOUTS[DEFAULT_LAYOUT])

    def _get_key(self, key):
        """Helper function to get the keycode and potential shift key for uppercase."""
        if key in self._KEY_TO_KEYCODEINFO:
            key_map_info = self._KEY_TO_KEYCODEINFO[key]
            if key_map_info.is_shifted:
                modifier = [self._KEY_TO_KEYCODEINFO["shift_l"].keycode]
            else:
                modifier = []
            return (key_map_info.keycode, modifier)
        return (None, [])

    def _press_key(self, key, state):
        self._ui.write(e.EV_KEY, key, 1 if state else 0)
        # self._ui.syn()

    """
    Send a unicode character.
    This depends on an IME such as iBus or fcitx5. iBus is used by GNOME, and fcitx5 by KDE.
    It assumes the default keybinding ctrl-shift-u, enter hex, enter is used, which is the default in both.
    From my testing, it works fine in using iBus and fcitx5, but in kitty terminal emulator, which uses
    the same keybinding, it's too fast for it to handle and ends up writing random stuff. I don't
    think there is a way to fix that other than increasing the delay.
    """

    def _send_unicode(self, hex):
        self.send_key_combination("ctrl_l(shift(u))")
        # self.delay()
        self.send_string(hex)
        # self.delay()
        self._send_char("\n")

    def _send_char(self, char):
        print("Sending char", char, char.encode("utf-8"))
        (base, mods) = self._get_key(char)

        # Key can be sent with a key combination
        if base is not None:
            for mod in mods:
                self._press_key(mod, True)
            # self.delay()
            self._press_key(base, True)
            self._press_key(base, False)
            for mod in mods:
                self._press_key(mod, False)

        # Key press can not be emulated - send unicode symbol instead
        else:
            # Convert to hex and remove leading "0x"
            unicode_hex = hex(ord(char))[2:]
            self._send_unicode(unicode_hex)

    def send_string(self, string):
        for key in self.with_delay(list(string)):
            self._send_char(key)
        self._ui.syn()

    def send_backspaces(self, count):
        for _ in range(count):
            self._send_char("\b")
        self._ui.syn()

    def send_key_combination(self, combo):
        # https://plover.readthedocs.io/en/latest/api/key_combo.html#module-plover.key_combo
        key_events = parse_key_combo(combo)

        for key, pressed in key_events:
            (base, _) = self._get_key(key)

            if base is not None:
                self._press_key(base, pressed)
            else:
                log.warning("Key " + key + " is not valid!")
        self._ui.syn()


class KeyboardCapture(Capture):
    _thread: threading.Thread | None
    _selector: selectors.BaseSelector
    # Pipe to signal _monitor_devices thread to stop
    # The thread will select() on this pipe to know when to stop
    _thread_read_pipe: int
    _thread_write_pipe: int

    def __init__(self):
        super().__init__()
        # This is based on the example from the python-evdev documentation: https://python-evdev.readthedocs.io/en/latest/tutorial.html#reading-events-from-multiple-devices-using-selectors
        self._devices = self._get_devices()
        self._running = False
        self._selector = selectors.DefaultSelector()
        self._thread = None
        self._thread_read_pipe, self._thread_write_pipe = os.pipe()
        self._selector.register(self._thread_read_pipe, selectors.EVENT_READ)
        self._res = util.find_ecodes_by_regex(r"KEY_.*")
        self._ui = UInput(self._res)
        self._suppressed_keys = []
        # The keycodes from evdev, e.g. e.KEY_A refers to the *physical* a, which corresponds with the qwerty layout.

    def _get_devices(self):
        input_devices = [InputDevice(path) for path in list_devices()]
        keyboard_devices = [dev for dev in input_devices if self._filter_devices(dev)]
        return keyboard_devices

    def _filter_devices(self, device):
        """
        Filter out devices that should not be grabbed and suppressed, to avoid output feeding into itself.
        """
        is_uinput = device.name == "py-evdev-uinput" or device.phys == "py-evdev-uinput"
        # Check for some common keys to make sure it's really a keyboard
        keys = device.capabilities().get(e.EV_KEY, [])
        keyboard_keys_present = any(
            key in keys
            for key in [e.KEY_ESC, e.KEY_SPACE, e.KEY_ENTER, e.KEY_LEFTSHIFT]
        )
        return not is_uinput and keyboard_keys_present

    def start(self):
        self._grab_devices()
        for device in self._devices:
            self._selector.register(device, selectors.EVENT_READ)
        self._thread = threading.Thread(target=self._run)
        self._thread.start()
        self._running = True
        log.debug("Done starting")

    def cancel(self):
        log.debug("Cancel")
        # Write some arbitrary data to the pipe to signal thread to stop
        os.write(self._thread_write_pipe, b"a")
        if self._thread is not None:
            self._thread.join()
            self._thread = None

        self._running = False

    def suppress(self, suppressed_keys=()):
        """
        UInput is not capable of suppressing only specific keys. To get around this, non-suppressed keys
        are passed through to a UInput device and emulated, while keys in this list get sent to plover.
        It does add a little bit of delay, but that is not noticeable.
        """
        self._suppressed_keys = suppressed_keys

    def _run(self):
        from evdev import categorize
        log.debug("Loop starting")
        keys_pressed_with_modifier: set[int] = set()
        with open("keylog.txt", "w") as keylog_file:
            try:
                while True:
                    for key, events in self._selector.select():
                        # print("Selector key:", key, "events:", events)
                        if key.fd == self._thread_read_pipe:
                            # Clear the pipe
                            os.read(key.fd, 999)
                            return
                        assert isinstance(key.fileobj, InputDevice)
                        device: InputDevice = key.fileobj
                        for event in device.read():
                            print("Event:", categorize(event), file=keylog_file, flush=True)
                            if event.type == e.EV_KEY:
                                # Debug quit key in case bug blocks user input
                                if event.code == e.KEY_F5:
                                    log.debug("Debug quit key pressed. Handling thread exiting...")

                                    for device in self._devices:
                                        device.ungrab()

                                    for device in self._devices:
                                        self._selector.unregister(device)
                                    self._devices = []

                                    self._running = False
                                    return

                                # The event.value == KeyEvent.key_up check in the if handles this case:
                                # Press a normal key, then modifier, then release key, then modifier. 
                                # If this was not here, because modifier is held when key is released, it is not sent to engine
                                # So engine thinks key is still held down
                                active_keys = device.active_keys()
                                modifier_active = any(key in MODIFIER_KEY_CODES for key in active_keys)
                                if event.code in MODIFIER_KEY_CODES:
                                    # Pass through modifier keys
                                    pass
                                elif modifier_active:
                                    print("modifier_active", file=keylog_file, flush=True)
                                    if event.value == KeyEvent.key_down and event.code in KEYCODE_TO_KEY:
                                        keys_pressed_with_modifier.add(event.code)
                                        print("New keys_pressed_with_modifier", keys_pressed_with_modifier, file=keylog_file, flush=True)
                                    elif event.value == KeyEvent.key_up:
                                        if event.code in keys_pressed_with_modifier:
                                            keys_pressed_with_modifier.discard(event.code)
                                            print("Key released with modifier. new keys_pressed_with_modifier", keys_pressed_with_modifier, file=keylog_file, flush=True)
                                        else:
                                            if event.code in KEYCODE_TO_KEY:
                                                key_name = KEYCODE_TO_KEY[event.code]
                                                self.key_up(key_name)
                                elif event.value == KeyEvent.key_up:
                                    if event.code in keys_pressed_with_modifier:
                                        keys_pressed_with_modifier.discard(event.code)
                                        print("Key released with modifier. new keys_pressed_with_modifier", keys_pressed_with_modifier, file=keylog_file, flush=True)
                                    elif event.code in KEYCODE_TO_KEY:
                                        key_name = KEYCODE_TO_KEY[event.code]
                                        self.key_up(key_name)
                                        if key_name in self._suppressed_keys:
                                            continue
                                elif event.value == KeyEvent.key_down and event.code in KEYCODE_TO_KEY:
                                    key_name = KEYCODE_TO_KEY[event.code]
                                    self.key_down(key_name)
                                    if key_name in self._suppressed_keys:
                                        continue
                            # Passthrough event
                            print("Passing through previous event", file=keylog_file, flush=True)
                            self._ui.write_event(event)
            finally:
                # Always ungrab devices to prevent exceptsions from causing input devices
                # to be blocked
                print("Ungrabbing devices")
                for device in self._devices:
                    try:
                        device.ungrab()
                        self._selector.unregister(device)
                    except:
                        log.error("Failed to ungrab device", exc_info=True)
                self._ui.close()