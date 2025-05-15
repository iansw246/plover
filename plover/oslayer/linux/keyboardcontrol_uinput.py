from collections.abc import Sequence
import os
import threading
from dataclasses import dataclass
import selectors
import string

from evdev import UInput, ecodes as e, util, InputDevice, list_devices, KeyEvent

from plover.output.keyboard import GenericKeyboardEmulation
from plover.machine.keyboard_capture import Capture
from plover.key_combo import parse_key_combo, KEYNAME_TO_CHAR
from plover import log

@dataclass
class KeyCodeInfo:
    keycode: int
    # Other keycodes that must be pressed with the keycode to send the key
    modifiers: Sequence[int] = ()

# Shared keys between all layouts
BASE_LAYOUT: dict[str, KeyCodeInfo] = {
    # Modifiers
    "alt_l": KeyCodeInfo(e.KEY_LEFTALT),
    "alt_r": KeyCodeInfo(e.KEY_RIGHTALT),
    "alt": KeyCodeInfo(e.KEY_LEFTALT),
    "ctrl_l": KeyCodeInfo(e.KEY_LEFTCTRL),
    "ctrl_r": KeyCodeInfo(e.KEY_RIGHTCTRL),
    "ctrl": KeyCodeInfo(e.KEY_LEFTCTRL),
    "control_l": KeyCodeInfo(e.KEY_LEFTCTRL),
    "control_r": KeyCodeInfo(e.KEY_RIGHTCTRL),
    "control": KeyCodeInfo(e.KEY_LEFTCTRL),
    "shift_l": KeyCodeInfo(e.KEY_LEFTSHIFT),
    "shift_r": KeyCodeInfo(e.KEY_RIGHTSHIFT),
    "shift": KeyCodeInfo(e.KEY_LEFTSHIFT),
    "super_l": KeyCodeInfo(e.KEY_LEFTMETA),
    "super_r": KeyCodeInfo(e.KEY_RIGHTMETA),
    "super": KeyCodeInfo(e.KEY_LEFTMETA),
    # Number row
    "`": KeyCodeInfo(e.KEY_GRAVE),
    "~": KeyCodeInfo(e.KEY_GRAVE, [e.KEY_LEFTSHIFT]),
    "1": KeyCodeInfo(e.KEY_1),
    "!": KeyCodeInfo(e.KEY_1, [e.KEY_LEFTSHIFT]),
    "2": KeyCodeInfo(e.KEY_2),
    "@": KeyCodeInfo(e.KEY_2, [e.KEY_LEFTSHIFT]),
    "3": KeyCodeInfo(e.KEY_3),
    "#": KeyCodeInfo(e.KEY_3, [e.KEY_LEFTSHIFT]),
    "4": KeyCodeInfo(e.KEY_4),
    "$": KeyCodeInfo(e.KEY_4, [e.KEY_LEFTSHIFT]),
    "5": KeyCodeInfo(e.KEY_5),
    "%": KeyCodeInfo(e.KEY_5, [e.KEY_LEFTSHIFT]),
    "6": KeyCodeInfo(e.KEY_6),
    "^": KeyCodeInfo(e.KEY_6, [e.KEY_LEFTSHIFT]),
    "7": KeyCodeInfo(e.KEY_7),
    "&": KeyCodeInfo(e.KEY_7, [e.KEY_LEFTSHIFT]),
    "8": KeyCodeInfo(e.KEY_8),
    "*": KeyCodeInfo(e.KEY_8, [e.KEY_LEFTSHIFT]),
    "9": KeyCodeInfo(e.KEY_9),
    "(": KeyCodeInfo(e.KEY_9, [e.KEY_LEFTSHIFT]),
    "0": KeyCodeInfo(e.KEY_0),
    ")": KeyCodeInfo(e.KEY_0, [e.KEY_LEFTSHIFT]),
    "-": KeyCodeInfo(e.KEY_MINUS),
    "_": KeyCodeInfo(e.KEY_MINUS, [e.KEY_LEFTSHIFT]),
    "=": KeyCodeInfo(e.KEY_EQUAL),
    "+": KeyCodeInfo(e.KEY_EQUAL, [e.KEY_LEFTSHIFT]),
    "\b": KeyCodeInfo(e.KEY_BACKSPACE),
    # Symbols
    " ": KeyCodeInfo(e.KEY_SPACE),
    "\n": KeyCodeInfo(e.KEY_ENTER),
    # https://github.com/openstenoproject/plover/blob/9b5a357f1fb57cb0a9a8596ae12cd1e84fcff6c4/plover/oslayer/osx/keyboardcontrol.py#L75
    # https://gist.github.com/jfortin42/68a1fcbf7738a1819eb4b2eef298f4f8
    "return": KeyCodeInfo(e.KEY_ENTER),
    "tab": KeyCodeInfo(e.KEY_TAB),
    "backspace": KeyCodeInfo(e.KEY_BACKSPACE),
    "delete": KeyCodeInfo(e.KEY_DELETE),
    "escape": KeyCodeInfo(e.KEY_ESC),
    "clear": KeyCodeInfo(e.KEY_CLEAR),
    # Navigation
    "up": KeyCodeInfo(e.KEY_UP),
    "down": KeyCodeInfo(e.KEY_DOWN),
    "left": KeyCodeInfo(e.KEY_LEFT),
    "right": KeyCodeInfo(e.KEY_RIGHT),
    "page_up": KeyCodeInfo(e.KEY_PAGEUP),
    "page_down": KeyCodeInfo(e.KEY_PAGEDOWN),
    "home": KeyCodeInfo(e.KEY_HOME),
    "insert": KeyCodeInfo(e.KEY_INSERT),
    "end": KeyCodeInfo(e.KEY_END),
    "space": KeyCodeInfo(e.KEY_SPACE),
    "print": KeyCodeInfo(e.KEY_PRINT),
    # Function keys
    "fn": KeyCodeInfo(e.KEY_FN),
    "f1": KeyCodeInfo(e.KEY_F1),
    "f2": KeyCodeInfo(e.KEY_F2),
    "f3": KeyCodeInfo(e.KEY_F3),
    "f4": KeyCodeInfo(e.KEY_F4),
    "f5": KeyCodeInfo(e.KEY_F5),
    "f6": KeyCodeInfo(e.KEY_F6),
    "f7": KeyCodeInfo(e.KEY_F7),
    "f8": KeyCodeInfo(e.KEY_F8),
    "f9": KeyCodeInfo(e.KEY_F9),
    "f10": KeyCodeInfo(e.KEY_F10),
    "f11": KeyCodeInfo(e.KEY_F11),
    "f12": KeyCodeInfo(e.KEY_F12),
    "f13": KeyCodeInfo(e.KEY_F13),
    "f14": KeyCodeInfo(e.KEY_F14),
    "f15": KeyCodeInfo(e.KEY_F15),
    "f16": KeyCodeInfo(e.KEY_F16),
    "f17": KeyCodeInfo(e.KEY_F17),
    "f18": KeyCodeInfo(e.KEY_F18),
    "f19": KeyCodeInfo(e.KEY_F19),
    "f20": KeyCodeInfo(e.KEY_F20),
    "f21": KeyCodeInfo(e.KEY_F21),
    "f22": KeyCodeInfo(e.KEY_F22),
    "f23": KeyCodeInfo(e.KEY_F23),
    "f24": KeyCodeInfo(e.KEY_F24),
    # Numpad
    "kp_1": KeyCodeInfo(e.KEY_KP1),
    "kp_2": KeyCodeInfo(e.KEY_KP2),
    "kp_3": KeyCodeInfo(e.KEY_KP3),
    "kp_4": KeyCodeInfo(e.KEY_KP4),
    "kp_5": KeyCodeInfo(e.KEY_KP5),
    "kp_6": KeyCodeInfo(e.KEY_KP6),
    "kp_7": KeyCodeInfo(e.KEY_KP7),
    "kp_8": KeyCodeInfo(e.KEY_KP8),
    "kp_9": KeyCodeInfo(e.KEY_KP9),
    "kp_0": KeyCodeInfo(e.KEY_KP0),
    "kp_add": KeyCodeInfo(e.KEY_KPPLUS),
    "kp_decimal": KeyCodeInfo(e.KEY_KPDOT),
    "kp_delete": KeyCodeInfo(e.KEY_DELETE),  # There is no KPDELETE
    "kp_divide": KeyCodeInfo(e.KEY_KPSLASH),
    "kp_enter": KeyCodeInfo(e.KEY_KPENTER),
    "kp_equal": KeyCodeInfo(e.KEY_KPEQUAL),
    "kp_multiply": KeyCodeInfo(e.KEY_KPASTERISK),
    "kp_subtract": KeyCodeInfo(e.KEY_KPMINUS),
    # Media keys
    "audioraisevolume": KeyCodeInfo(e.KEY_VOLUMEUP),
    "audiolowervolume": KeyCodeInfo(e.KEY_VOLUMEDOWN),
    "monbrightnessup": KeyCodeInfo(e.KEY_BRIGHTNESSUP),
    "monbrightnessdown": KeyCodeInfo(e.KEY_BRIGHTNESSDOWN),
    "audiomute": KeyCodeInfo(e.KEY_MUTE),
    "num_lock": KeyCodeInfo(e.KEY_NUMLOCK),
    "eject": KeyCodeInfo(e.KEY_EJECTCD),
    "audiopause": KeyCodeInfo(e.KEY_PAUSE),
    "audionext": KeyCodeInfo(e.KEY_NEXT),
    "audioplay": KeyCodeInfo(e.KEY_PLAY),
    "audiorewind": KeyCodeInfo(e.KEY_REWIND),
    "kbdbrightnessup": KeyCodeInfo(e.KEY_KBDILLUMUP),
    "kbdbrightnessdown": KeyCodeInfo(e.KEY_KBDILLUMDOWN),
}

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
        # First row
        "q": KeyCodeInfo(e.KEY_Q),
        "Q": KeyCodeInfo(e.KEY_Q, [e.KEY_LEFTSHIFT]),
        "w": KeyCodeInfo(e.KEY_W),
        "W": KeyCodeInfo(e.KEY_W, [e.KEY_LEFTSHIFT]),
        "e": KeyCodeInfo(e.KEY_E),
        "E": KeyCodeInfo(e.KEY_E, [e.KEY_LEFTSHIFT]),
        "r": KeyCodeInfo(e.KEY_R),
        "R": KeyCodeInfo(e.KEY_R, [e.KEY_LEFTSHIFT]),
        "t": KeyCodeInfo(e.KEY_T),
        "T": KeyCodeInfo(e.KEY_T, [e.KEY_LEFTSHIFT]),
        "y": KeyCodeInfo(e.KEY_Y),
        "Y": KeyCodeInfo(e.KEY_Y, [e.KEY_LEFTSHIFT]),
        "u": KeyCodeInfo(e.KEY_U),
        "U": KeyCodeInfo(e.KEY_U, [e.KEY_LEFTSHIFT]),
        "i": KeyCodeInfo(e.KEY_I),
        "I": KeyCodeInfo(e.KEY_I, [e.KEY_LEFTSHIFT]),
        "o": KeyCodeInfo(e.KEY_O),
        "O": KeyCodeInfo(e.KEY_O, [e.KEY_LEFTSHIFT]),
        "p": KeyCodeInfo(e.KEY_P),
        "P": KeyCodeInfo(e.KEY_P, [e.KEY_LEFTSHIFT]),
        "[": KeyCodeInfo(e.KEY_LEFTBRACE),
        "{": KeyCodeInfo(e.KEY_LEFTBRACE, [e.KEY_LEFTSHIFT]),
        "]": KeyCodeInfo(e.KEY_RIGHTBRACE),
        "}": KeyCodeInfo(e.KEY_RIGHTBRACE, [e.KEY_LEFTSHIFT]),
        "\\": KeyCodeInfo(e.KEY_BACKSLASH),
        "|": KeyCodeInfo(e.KEY_BACKSLASH, [e.KEY_LEFTSHIFT]),
        # Second row
        "a": KeyCodeInfo(e.KEY_A),
        "A": KeyCodeInfo(e.KEY_A, [e.KEY_LEFTSHIFT]),
        "s": KeyCodeInfo(e.KEY_S),
        "S": KeyCodeInfo(e.KEY_S, [e.KEY_LEFTSHIFT]),
        "d": KeyCodeInfo(e.KEY_D),
        "D": KeyCodeInfo(e.KEY_D, [e.KEY_LEFTSHIFT]),
        "f": KeyCodeInfo(e.KEY_F),
        "F": KeyCodeInfo(e.KEY_F, [e.KEY_LEFTSHIFT]),
        "g": KeyCodeInfo(e.KEY_G),
        "G": KeyCodeInfo(e.KEY_G, [e.KEY_LEFTSHIFT]),
        "h": KeyCodeInfo(e.KEY_H),
        "H": KeyCodeInfo(e.KEY_H, [e.KEY_LEFTSHIFT]),
        "j": KeyCodeInfo(e.KEY_J),
        "J": KeyCodeInfo(e.KEY_J, [e.KEY_LEFTSHIFT]),
        "k": KeyCodeInfo(e.KEY_K),
        "K": KeyCodeInfo(e.KEY_K, [e.KEY_LEFTSHIFT]),
        "l": KeyCodeInfo(e.KEY_L),
        "L": KeyCodeInfo(e.KEY_L, [e.KEY_LEFTSHIFT]),
        ";": KeyCodeInfo(e.KEY_SEMICOLON),
        ":": KeyCodeInfo(e.KEY_SEMICOLON, [e.KEY_LEFTSHIFT]),
        "'": KeyCodeInfo(e.KEY_APOSTROPHE),
        "\"": KeyCodeInfo(e.KEY_APOSTROPHE, [e.KEY_LEFTSHIFT]),
        # Third row
        "z": KeyCodeInfo(e.KEY_Z),
        "Z": KeyCodeInfo(e.KEY_Z, [e.KEY_LEFTSHIFT]),
        "x": KeyCodeInfo(e.KEY_X),
        "X": KeyCodeInfo(e.KEY_X, [e.KEY_LEFTSHIFT]),
        "c": KeyCodeInfo(e.KEY_C),
        "C": KeyCodeInfo(e.KEY_C, [e.KEY_LEFTSHIFT]),
        "v": KeyCodeInfo(e.KEY_V),
        "V": KeyCodeInfo(e.KEY_V, [e.KEY_LEFTSHIFT]),
        "b": KeyCodeInfo(e.KEY_B),
        "B": KeyCodeInfo(e.KEY_B, [e.KEY_LEFTSHIFT]),
        "n": KeyCodeInfo(e.KEY_N),
        "N": KeyCodeInfo(e.KEY_N, [e.KEY_LEFTSHIFT]),
        "m": KeyCodeInfo(e.KEY_M),
        "M": KeyCodeInfo(e.KEY_M, [e.KEY_LEFTSHIFT]),
        ",": KeyCodeInfo(e.KEY_COMMA),
        "<": KeyCodeInfo(e.KEY_COMMA, [e.KEY_LEFTSHIFT]),
        ".": KeyCodeInfo(e.KEY_DOT),
        ">": KeyCodeInfo(e.KEY_DOT, [e.KEY_LEFTSHIFT]),
        "/": KeyCodeInfo(e.KEY_SLASH),
        "?": KeyCodeInfo(e.KEY_SLASH, [e.KEY_LEFTSHIFT]),
    },
    "qwertz": {
        **BASE_LAYOUT,
        # Number row
        "°": KeyCodeInfo(e.KEY_GRAVE, [e.KEY_LEFTSHIFT]),
        "1": KeyCodeInfo(e.KEY_1),
        "!": KeyCodeInfo(e.KEY_1, [e.KEY_LEFTSHIFT]),
        "2": KeyCodeInfo(e.KEY_2),
        "\"": KeyCodeInfo(e.KEY_2, [e.KEY_LEFTSHIFT]),
        "3": KeyCodeInfo(e.KEY_3),
        "§": KeyCodeInfo(e.KEY_3, [e.KEY_LEFTSHIFT]),
        "4": KeyCodeInfo(e.KEY_4),
        "$": KeyCodeInfo(e.KEY_4, [e.KEY_LEFTSHIFT]),
        "5": KeyCodeInfo(e.KEY_5),
        "%": KeyCodeInfo(e.KEY_5, [e.KEY_LEFTSHIFT]),
        "6": KeyCodeInfo(e.KEY_6),
        "&": KeyCodeInfo(e.KEY_6, [e.KEY_LEFTSHIFT]),
        "7": KeyCodeInfo(e.KEY_7),
        "/": KeyCodeInfo(e.KEY_7, [e.KEY_LEFTSHIFT]),
        "8": KeyCodeInfo(e.KEY_8),
        "(": KeyCodeInfo(e.KEY_8, [e.KEY_LEFTSHIFT]),
        "9": KeyCodeInfo(e.KEY_9),
        ")": KeyCodeInfo(e.KEY_9, [e.KEY_LEFTSHIFT]),
        "0": KeyCodeInfo(e.KEY_0),
        "=": KeyCodeInfo(e.KEY_0, [e.KEY_LEFTSHIFT]),
        "ß": KeyCodeInfo(e.KEY_MINUS),
        "?": KeyCodeInfo(e.KEY_MINUS, [e.KEY_LEFTSHIFT]),
        "`": KeyCodeInfo(e.KEY_EQUAL, [e.KEY_LEFTSHIFT]),
        "\b": KeyCodeInfo(e.KEY_BACKSPACE),
        # Top row
        "q": KeyCodeInfo(e.KEY_Q),
        "Q": KeyCodeInfo(e.KEY_Q, [e.KEY_LEFTSHIFT]),
        "w": KeyCodeInfo(e.KEY_W),
        "W": KeyCodeInfo(e.KEY_W, [e.KEY_LEFTSHIFT]),
        "e": KeyCodeInfo(e.KEY_E),
        "E": KeyCodeInfo(e.KEY_E, [e.KEY_LEFTSHIFT]),
        "r": KeyCodeInfo(e.KEY_R),
        "R": KeyCodeInfo(e.KEY_R, [e.KEY_LEFTSHIFT]),
        "t": KeyCodeInfo(e.KEY_T),
        "T": KeyCodeInfo(e.KEY_T, [e.KEY_LEFTSHIFT]),
        "z": KeyCodeInfo(e.KEY_Y),
        "Z": KeyCodeInfo(e.KEY_Y, [e.KEY_LEFTSHIFT]),
        "u": KeyCodeInfo(e.KEY_U),
        "U": KeyCodeInfo(e.KEY_U, [e.KEY_LEFTSHIFT]),
        "i": KeyCodeInfo(e.KEY_I),
        "I": KeyCodeInfo(e.KEY_I, [e.KEY_LEFTSHIFT]),
        "o": KeyCodeInfo(e.KEY_O),
        "O": KeyCodeInfo(e.KEY_O, [e.KEY_LEFTSHIFT]),
        "p": KeyCodeInfo(e.KEY_P),
        "P": KeyCodeInfo(e.KEY_P, [e.KEY_LEFTSHIFT]),
        "ü": KeyCodeInfo(e.KEY_LEFTBRACE),
        "Ü": KeyCodeInfo(e.KEY_LEFTBRACE, [e.KEY_LEFTSHIFT]),
        "+": KeyCodeInfo(e.KEY_RIGHTBRACE),
        "*": KeyCodeInfo(e.KEY_RIGHTBRACE, [e.KEY_LEFTSHIFT]),
        "#": KeyCodeInfo(e.KEY_BACKSLASH),
        "'": KeyCodeInfo(e.KEY_BACKSLASH, [e.KEY_LEFTSHIFT]),
        # Middle row
        "a": KeyCodeInfo(e.KEY_A),
        "A": KeyCodeInfo(e.KEY_A, [e.KEY_LEFTSHIFT]),
        "s": KeyCodeInfo(e.KEY_S),
        "S": KeyCodeInfo(e.KEY_S, [e.KEY_LEFTSHIFT]),
        "d": KeyCodeInfo(e.KEY_D),
        "D": KeyCodeInfo(e.KEY_D, [e.KEY_LEFTSHIFT]),
        "f": KeyCodeInfo(e.KEY_F),
        "F": KeyCodeInfo(e.KEY_F, [e.KEY_LEFTSHIFT]),
        "g": KeyCodeInfo(e.KEY_G),
        "G": KeyCodeInfo(e.KEY_G, [e.KEY_LEFTSHIFT]),
        "h": KeyCodeInfo(e.KEY_H),
        "H": KeyCodeInfo(e.KEY_H, [e.KEY_LEFTSHIFT]),
        "j": KeyCodeInfo(e.KEY_J),
        "J": KeyCodeInfo(e.KEY_J, [e.KEY_LEFTSHIFT]),
        "k": KeyCodeInfo(e.KEY_K),
        "K": KeyCodeInfo(e.KEY_K, [e.KEY_LEFTSHIFT]),
        "l": KeyCodeInfo(e.KEY_L),
        "L": KeyCodeInfo(e.KEY_L, [e.KEY_LEFTSHIFT]),
        "ö": KeyCodeInfo(e.KEY_SEMICOLON),
        "Ö": KeyCodeInfo(e.KEY_SEMICOLON, [e.KEY_LEFTSHIFT]),
        "ä": KeyCodeInfo(e.KEY_APOSTROPHE),
        "Ä": KeyCodeInfo(e.KEY_APOSTROPHE),
        # Bottom row
        "y": KeyCodeInfo(e.KEY_Z),
        "Y": KeyCodeInfo(e.KEY_Z, [e.KEY_LEFTSHIFT]),
        "x": KeyCodeInfo(e.KEY_X),
        "X": KeyCodeInfo(e.KEY_X, [e.KEY_LEFTSHIFT]),
        "c": KeyCodeInfo(e.KEY_C),
        "C": KeyCodeInfo(e.KEY_C, [e.KEY_LEFTSHIFT]),
        "v": KeyCodeInfo(e.KEY_V),
        "V": KeyCodeInfo(e.KEY_V, [e.KEY_LEFTSHIFT]),
        "b": KeyCodeInfo(e.KEY_B),
        "B": KeyCodeInfo(e.KEY_B, [e.KEY_LEFTSHIFT]),
        "n": KeyCodeInfo(e.KEY_N),
        "N": KeyCodeInfo(e.KEY_N, [e.KEY_LEFTSHIFT]),
        "m": KeyCodeInfo(e.KEY_M),
        "M": KeyCodeInfo(e.KEY_M, [e.KEY_LEFTSHIFT]),
        ",": KeyCodeInfo(e.KEY_COMMA),
        "<": KeyCodeInfo(e.KEY_COMMA, [e.KEY_LEFTSHIFT]),
        ".": KeyCodeInfo(e.KEY_DOT),
        ">": KeyCodeInfo(e.KEY_DOT, [e.KEY_LEFTSHIFT]),
        "-": KeyCodeInfo(e.KEY_SLASH),
        "_": KeyCodeInfo(e.KEY_SLASH, [e.KEY_LEFTSHIFT]),
    },
    "colemak": {
        **BASE_LAYOUT,
        # Top row
        "q": KeyCodeInfo(e.KEY_Q),
        "Q": KeyCodeInfo(e.KEY_Q, [e.KEY_LEFTSHIFT]),
        "w": KeyCodeInfo(e.KEY_W),
        "W": KeyCodeInfo(e.KEY_W, [e.KEY_LEFTSHIFT]),
        "f": KeyCodeInfo(e.KEY_E),
        "F": KeyCodeInfo(e.KEY_E, [e.KEY_LEFTSHIFT]),
        "p": KeyCodeInfo(e.KEY_R),
        "P": KeyCodeInfo(e.KEY_R, [e.KEY_LEFTSHIFT]),
        "g": KeyCodeInfo(e.KEY_T),
        "G": KeyCodeInfo(e.KEY_T, [e.KEY_LEFTSHIFT]),
        "j": KeyCodeInfo(e.KEY_Y),
        "J": KeyCodeInfo(e.KEY_Y, [e.KEY_LEFTSHIFT]),
        "l": KeyCodeInfo(e.KEY_U),
        "L": KeyCodeInfo(e.KEY_U, [e.KEY_LEFTSHIFT]),
        "u": KeyCodeInfo(e.KEY_I),
        "U": KeyCodeInfo(e.KEY_I, [e.KEY_LEFTSHIFT]),
        "y": KeyCodeInfo(e.KEY_O),
        "Y": KeyCodeInfo(e.KEY_O, [e.KEY_LEFTSHIFT]),
        ";": KeyCodeInfo(e.KEY_O),
        ":": KeyCodeInfo(e.KEY_O, [e.KEY_LEFTSHIFT]),
        "[": KeyCodeInfo(e.KEY_LEFTBRACE),
        "{": KeyCodeInfo(e.KEY_LEFTBRACE, [e.KEY_LEFTSHIFT]),
        "]": KeyCodeInfo(e.KEY_RIGHTBRACE),
        "}": KeyCodeInfo(e.KEY_RIGHTBRACE, [e.KEY_LEFTSHIFT]),
        "\\": KeyCodeInfo(e.KEY_BACKSLASH),
        "|": KeyCodeInfo(e.KEY_BACKSLASH, [e.KEY_LEFTSHIFT]),
        # Middle row
        "a": KeyCodeInfo(e.KEY_A),
        "A": KeyCodeInfo(e.KEY_A, [e.KEY_LEFTSHIFT]),
        "r": KeyCodeInfo(e.KEY_S),
        "R": KeyCodeInfo(e.KEY_S, [e.KEY_LEFTSHIFT]),
        "s": KeyCodeInfo(e.KEY_D),
        "S": KeyCodeInfo(e.KEY_D, [e.KEY_LEFTSHIFT]),
        "t": KeyCodeInfo(e.KEY_F),
        "T": KeyCodeInfo(e.KEY_F, [e.KEY_LEFTSHIFT]),
        "d": KeyCodeInfo(e.KEY_G),
        "D": KeyCodeInfo(e.KEY_G, [e.KEY_LEFTSHIFT]),
        "h": KeyCodeInfo(e.KEY_H),
        "H": KeyCodeInfo(e.KEY_H, [e.KEY_LEFTSHIFT]),
        "n": KeyCodeInfo(e.KEY_J),
        "N": KeyCodeInfo(e.KEY_J, [e.KEY_LEFTSHIFT]),
        "e": KeyCodeInfo(e.KEY_K),
        "E": KeyCodeInfo(e.KEY_K, [e.KEY_LEFTSHIFT]),
        "i": KeyCodeInfo(e.KEY_L),
        "I": KeyCodeInfo(e.KEY_L, [e.KEY_LEFTSHIFT]),
        "o": KeyCodeInfo(e.KEY_SEMICOLON),
        "O": KeyCodeInfo(e.KEY_SEMICOLON, [e.KEY_LEFTSHIFT]),
        "'": KeyCodeInfo(e.KEY_APOSTROPHE),
        "\"": KeyCodeInfo(e.KEY_APOSTROPHE, [e.KEY_LEFTSHIFT]),
        # Bottom row
        "z": KeyCodeInfo(e.KEY_Z),
        "Z": KeyCodeInfo(e.KEY_Z, [e.KEY_LEFTSHIFT]),
        "x": KeyCodeInfo(e.KEY_X),
        "X": KeyCodeInfo(e.KEY_X, [e.KEY_LEFTSHIFT]),
        "c": KeyCodeInfo(e.KEY_C),
        "C": KeyCodeInfo(e.KEY_C, [e.KEY_LEFTSHIFT]),
        "v": KeyCodeInfo(e.KEY_V),
        "V": KeyCodeInfo(e.KEY_V, [e.KEY_LEFTSHIFT]),
        "b": KeyCodeInfo(e.KEY_B),
        "B": KeyCodeInfo(e.KEY_B, [e.KEY_LEFTSHIFT]),
        "k": KeyCodeInfo(e.KEY_N),
        "K": KeyCodeInfo(e.KEY_N, [e.KEY_LEFTSHIFT]),
        "m": KeyCodeInfo(e.KEY_M),
        "M": KeyCodeInfo(e.KEY_M, [e.KEY_LEFTSHIFT]),
        ",": KeyCodeInfo(e.KEY_COMMA),
        "<": KeyCodeInfo(e.KEY_COMMA, [e.KEY_LEFTSHIFT]),
        ".": KeyCodeInfo(e.KEY_DOT),
        ">": KeyCodeInfo(e.KEY_DOT, [e.KEY_LEFTSHIFT]),
        "/": KeyCodeInfo(e.KEY_SLASH),
        "?": KeyCodeInfo(e.KEY_SLASH, [e.KEY_LEFTSHIFT]),
    },
    "colemak-dh": {
        **BASE_LAYOUT,
        # Top row
        "q": KeyCodeInfo(e.KEY_Q),
        "Q": KeyCodeInfo(e.KEY_Q, [e.KEY_LEFTSHIFT]),
        "w": KeyCodeInfo(e.KEY_W),
        "W": KeyCodeInfo(e.KEY_W, [e.KEY_LEFTSHIFT]),
        "f": KeyCodeInfo(e.KEY_E),
        "F": KeyCodeInfo(e.KEY_E, [e.KEY_LEFTSHIFT]),
        "p": KeyCodeInfo(e.KEY_R),
        "P": KeyCodeInfo(e.KEY_R, [e.KEY_LEFTSHIFT]),
        "b": KeyCodeInfo(e.KEY_T),
        "B": KeyCodeInfo(e.KEY_T, [e.KEY_LEFTSHIFT]),
        "j": KeyCodeInfo(e.KEY_Y),
        "J": KeyCodeInfo(e.KEY_Y, [e.KEY_LEFTSHIFT]),
        "l": KeyCodeInfo(e.KEY_U),
        "L": KeyCodeInfo(e.KEY_U, [e.KEY_LEFTSHIFT]),
        "u": KeyCodeInfo(e.KEY_I),
        "U": KeyCodeInfo(e.KEY_I, [e.KEY_LEFTSHIFT]),
        "y": KeyCodeInfo(e.KEY_O),
        "Y": KeyCodeInfo(e.KEY_O, [e.KEY_LEFTSHIFT]),
        ";": KeyCodeInfo(e.KEY_P),
        ":": KeyCodeInfo(e.KEY_P, [e.KEY_LEFTSHIFT]),
        "[": KeyCodeInfo(e.KEY_LEFTBRACE),
        "{": KeyCodeInfo(e.KEY_LEFTBRACE, [e.KEY_LEFTSHIFT]),
        "]": KeyCodeInfo(e.KEY_RIGHTBRACE),
        "}": KeyCodeInfo(e.KEY_RIGHTBRACE, [e.KEY_LEFTSHIFT]),
        "\\": KeyCodeInfo(e.KEY_BACKSLASH),
        "|": KeyCodeInfo(e.KEY_BACKSLASH, [e.KEY_LEFTSHIFT]),
        # Middle row
        "a": KeyCodeInfo(e.KEY_A),
        "A": KeyCodeInfo(e.KEY_A, [e.KEY_LEFTSHIFT]),
        "r": KeyCodeInfo(e.KEY_S),
        "R": KeyCodeInfo(e.KEY_S, [e.KEY_LEFTSHIFT]),
        "s": KeyCodeInfo(e.KEY_D),
        "S": KeyCodeInfo(e.KEY_D, [e.KEY_LEFTSHIFT]),
        "t": KeyCodeInfo(e.KEY_F),
        "T": KeyCodeInfo(e.KEY_F, [e.KEY_LEFTSHIFT]),
        "g": KeyCodeInfo(e.KEY_G),
        "G": KeyCodeInfo(e.KEY_G, [e.KEY_LEFTSHIFT]),
        "m": KeyCodeInfo(e.KEY_H),
        "M": KeyCodeInfo(e.KEY_H, [e.KEY_LEFTSHIFT]),
        "n": KeyCodeInfo(e.KEY_J),
        "N": KeyCodeInfo(e.KEY_J, [e.KEY_LEFTSHIFT]),
        "e": KeyCodeInfo(e.KEY_K),
        "E": KeyCodeInfo(e.KEY_K, [e.KEY_LEFTSHIFT]),
        "i": KeyCodeInfo(e.KEY_L),
        "I": KeyCodeInfo(e.KEY_L, [e.KEY_LEFTSHIFT]),
        "o": KeyCodeInfo(e.KEY_SEMICOLON),
        "O": KeyCodeInfo(e.KEY_SEMICOLON, [e.KEY_LEFTSHIFT]),
        "'": KeyCodeInfo(e.KEY_APOSTROPHE),
        "\"": KeyCodeInfo(e.KEY_APOSTROPHE, [e.KEY_LEFTSHIFT]),
        # Bottom row
        "x": KeyCodeInfo(e.KEY_Z),
        "X": KeyCodeInfo(e.KEY_Z, [e.KEY_LEFTSHIFT]),
        "c": KeyCodeInfo(e.KEY_X),
        "C": KeyCodeInfo(e.KEY_X, [e.KEY_LEFTSHIFT]),
        "d": KeyCodeInfo(e.KEY_C),
        "D": KeyCodeInfo(e.KEY_C, [e.KEY_LEFTSHIFT]),
        "v": KeyCodeInfo(e.KEY_V),
        "V": KeyCodeInfo(e.KEY_V, [e.KEY_LEFTSHIFT]),
        "z": KeyCodeInfo(e.KEY_B),  # less than-key
        "Z": KeyCodeInfo(e.KEY_B, [e.KEY_LEFTSHIFT]),
        "k": KeyCodeInfo(e.KEY_N),
        "K": KeyCodeInfo(e.KEY_N, [e.KEY_LEFTSHIFT]),
        "h": KeyCodeInfo(e.KEY_M),
        "H": KeyCodeInfo(e.KEY_M, [e.KEY_LEFTSHIFT]),
        ",": KeyCodeInfo(e.KEY_COMMA),
        "<": KeyCodeInfo(e.KEY_COMMA, [e.KEY_LEFTSHIFT]),
        ".": KeyCodeInfo(e.KEY_DOT),
        ">": KeyCodeInfo(e.KEY_DOT, [e.KEY_LEFTSHIFT]),
        "/": KeyCodeInfo(e.KEY_SLASH),
        "?": KeyCodeInfo(e.KEY_SLASH, [e.KEY_LEFTSHIFT]),
    },
}

# Ignore keys with modifiers
KEYCODES_TO_SUPRESS = {v.keycode: key for key, v in LAYOUTS[DEFAULT_LAYOUT].items() if len(v.modifiers) == 0}
# Make sure no keys missing. Last 5 are "\t\n\r\x0b\x0c" which don't need to be handled
assert all(c in LAYOUTS[DEFAULT_LAYOUT].keys() for c in string.printable[:-5])

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
        """Helper function to get the keycode and potential modifiers for a key."""
        if key in self._KEY_TO_KEYCODEINFO:
            key_map_info = self._KEY_TO_KEYCODEINFO[key]
            return (key_map_info.keycode, key_map_info.modifiers)
        return (None, [])

    def _press_key(self, key, state):
        self._ui.write(e.EV_KEY, key, 1 if state else 0)
        self._ui.syn()

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
        self.delay()
        self.send_string(hex)
        self.delay()
        self._send_char("\n")

    def _send_char(self, char):
        (base, mods) = self._get_key(char)

        # Key can be sent with a key combination
        if base is not None:
            for mod in mods:
                self._press_key(mod, True)
            self.delay()
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

    def send_backspaces(self, count):
        for _ in range(count):
            self._send_char("\b")

    def send_key_combination(self, combo):
        # https://plover.readthedocs.io/en/latest/api/key_combo.html#module-plover.key_combo
        key_events = parse_key_combo(combo)

        for key, pressed in self.with_delay(key_events):
            (base, _) = self._get_key(key)

            if base is not None:
                self._press_key(base, pressed)
            else:
                log.warning("Key " + key + " is not valid!")

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
        capabilities = device.capabilities()
        is_uinput = device.name == "py-evdev-uinput" or device.phys == "py-evdev-uinput"
        # Check for some common keys to make sure it's really a keyboard
        keys = device.capabilities().get(e.EV_KEY, [])
        keyboard_keys_present = any(
            key in keys
            for key in [e.KEY_ESC, e.KEY_SPACE, e.KEY_ENTER, e.KEY_LEFTSHIFT]
        )
        return not is_uinput and keyboard_keys_present

    def _grab_devices(self):
        """Grab all devices, waiting for each device to stop having keys pressed.
        If a device is grabbed when keys are being pressed, the key will
        appear to be always pressed down until the device is ungrabbed and the
        key is pressed again.
        See https://stackoverflow.com/questions/41995349/why-does-ioctlfd-eviocgrab-1-cause-key-spam-sometimes
        There is likely a race condition here between checking active keys and
        actually grabbing the device, but it appears to work fine.
        """
        for device in self._devices:
            if len(device.active_keys()) > 0:
                for _ in device.read_loop():
                    if len(device.active_keys()) == 0:
                        # No keys are pressed. Grab the device
                        break
            device.grab()

    def start(self):
        self._grab_devices()
        for device in self._devices:
            self._selector.register(device, selectors.EVENT_READ)
        self._thread = threading.Thread(target=self._run)
        self._thread.start()
        self._running = True

    def cancel(self):
        # Write some arbitrary data to the pipe to signal the _run thread to stop
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
        keys_pressed_with_modifier: set[int] = set()
        down_modifier_keys: set[int] = set()

        def _should_suppress(event) -> bool:
            if event.code in MODIFIER_KEY_CODES:
                # Can't use if-else because there is a third case: key_hold
                if event.value == KeyEvent.key_down:
                    down_modifier_keys.add(event.code)
                elif event.value == KeyEvent.key_up:
                    down_modifier_keys.discard(event.code)
                return False
            key = KEYCODES_TO_SUPRESS.get(event.code, None)
            if key is None:
                # Key is unhandled. Don't suppress
                return False
            if event.value == KeyEvent.key_down and down_modifier_keys:
                keys_pressed_with_modifier.add(event.code)
                return False
            if event.value == KeyEvent.key_up and event.code in keys_pressed_with_modifier:
                # Must pass through key up event if key was pressed with modifier
                # or else it will stay pressed down and start repeating.
                # Must release even if modifier key was released first
                keys_pressed_with_modifier.discard(event.code)
                return False
            suppressed = key in self._suppressed_keys
            return suppressed

        try:
            while True:
                for key, events in self._selector.select():
                    if key.fd == self._thread_read_pipe:
                        # Clear the pipe
                        os.read(key.fd, 999)
                        return
                    assert isinstance(key.fileobj, InputDevice)
                    device: InputDevice = key.fileobj
                    for event in device.read():
                        # if event.type == e.EV_KEY and _should_suppress(event):
                        if event.type == e.EV_KEY:
                            key_name = KEYCODES_TO_SUPRESS[event.code]
                            if event.value == KeyEvent.key_down:
                                self.key_down(key_name)
                            elif event.value == KeyEvent.key_up:
                                self.key_up(key_name)
                            if _should_suppress(event):
                                # Don't passthrough. Skip rest of this loop
                                continue

                        # Passthrough event
                        self._ui.write_event(event)
        finally:
            # Always ungrab devices to prevent exceptions in the _run loop
            # from causing grabbed input devices to be blocked
            for device in self._devices:
                try:
                    device.ungrab()
                    self._selector.unregister(device)
                except:
                    log.error("Failed to ungrab device", exc_info=True)
            self._ui.close()