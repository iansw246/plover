from dataclasses import dataclass
from typing import Sequence
import string
import array
import collections
import contextlib
import mmap
import os
import socket
import struct
import selectors
import threading

from xkbcommon import xkb
from evdev import ecodes as e, util

@dataclass
class KeyCodeInfo:
    keycode: int
    # Other keycodes that must be pressed with the keycode to send the key
    modifiers: Sequence[int] = ()

WAYLAND_MESSAGE_HEADER_SIZE_BYTES = 8

DISPLAY_ID = 1
REGISTRY_ID = 2
SYNC_ID = 3
SEAT_ID = 4
KEYBOARD_ID = 5

# Offset between xkbcommon keycodes and Linux EV keycodes
# Subtract this value from xkbcommon keycodes to get Linux EV keycodes
XKB_TO_EV_KEYCODE_OFFSET = 8

# TODO: Find way to get this from Wayland keymap
# Code for retrieving the key map and parsing it is already implemented.
# Just need a way to avoid double connections from the Capture and Emulation classes.
# Perhaps a persistent background thread with a connection to Wayland that updates global state?
MODIFIER_KEY_CODES: set[int] = {
    e.KEY_LEFTSHIFT, e.KEY_RIGHTSHIFT,
    e.KEY_LEFTCTRL, e.KEY_RIGHTCTRL,
    e.KEY_LEFTALT, e.KEY_RIGHTALT,
    e.KEY_LEFTMETA, e.KEY_RIGHTMETA,
}

VALID_EV_KEYCODES: set[int] = set(util.find_ecodes_by_regex(r"KEY_.*")[1])

WAYLAND_AUTO_LAYOUT_NAME = "wayland-auto"

# Additional aliases for xkbcommon keysyms
# Keys beginning with "XF86" are handled as a special case during xkbcommon keymap processing
# For each xkbcommon keysyms, the lowercase of the symbol name is already added to the keymap by the code
XKB_KEY_NAME_TO_ALIASES: dict[str, list[str]] = {
    "Return": ["\n"],
    "Control_L": ["ctrl", "ctrl_l"],
    "Shift_L": ["shift"],
    "Super_L": ["super", "windows", "command"],
    "Alt_L": ["alt", "option"],
    "Tab": ["\t"],
    "Next": ["page_down"],
    "Prior": ["page_up"],
    "KP_Home": ["kp_7"],
    "KP_Up": ["kp_8"],
    "KP_Prior": ["kp_9"],
    "KP_Left": ["kp_4"],
    "KP_Begin": ["kp_5"],
    "KP_Right": ["kp_6"],
    "KP_End": ["kp_1"],
    "KP_Down": ["kp_2"],
    "KP_Next": ["kp_3"],
    "KP_Insert": ["kp_0"],
    "KP_Delete": ["kp_dot", "kp_decimal"],
}

def xkb_keycode_to_ev_keycode(keycode: int):
    return keycode - XKB_TO_EV_KEYCODE_OFFSET

def ev_keycode_to_xkb_keycode(keycode: int):
    return keycode + XKB_TO_EV_KEYCODE_OFFSET

def round_up_power_of_two(value: int, multiple: int):
    """Round `value` up to the nearest multiple of `multiple`.
    `multiple` must be positive and a power of 2"""
    assert multiple & 1 == 0
    return (value + multiple - 1) & ~(multiple - 1)

class WaylandConnection:
    """Context manager for connecting to the Wayland server.
    
    Useful resources:
    - https://wayland-book.com/
    - https://wayland.freedesktop.org/docs/html/ch04.html#sect-Protocol-Wire-Format
    - https://wayland.app/protocols/wayland
    """
    fd_queue: collections.deque[int]
    _wayland_socket: socket.socket
    _shutdown_pipe_read: int
    _shutdown_pipe_write: int
    _selector: selectors.BaseSelector

    def __init__(self):
        self.fd_queue = collections.deque()
        self._shutdown_pipe_read, self._shutdown_pipe_write = os.pipe()
        self._selector = selectors.DefaultSelector()


    def __enter__(self):
        # Find socket path following libwayland (https://wayland-book.com/protocol-design/wire-protocol.html#transports)
        xdg_runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "")
        wayland_display = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
        socket_path = os.path.join(xdg_runtime_dir, wayland_display)

        self._wayland_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._wayland_socket.connect(socket_path)

        self._selector.register(self._wayland_socket, selectors.EVENT_READ)
        self._selector.register(self._shutdown_pipe_read, selectors.EVENT_READ)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self._selector.close()
        finally:
            self._wayland_socket.shutdown(socket.SHUT_RDWR)
            self._wayland_socket.close()
            os.close(self._shutdown_pipe_read)
            os.close(self._shutdown_pipe_write)

    def recv_message(self):
        """Receive an event from the Wayland server. Blocks until a complete message is received.
        
        Returns:
            A tuple of (object_id, length, opcode, event_data_bytes)
        """
        # The only event with fds that we care about is wl_keyboard::keymap which only has one fd
        # In each message, we only need to receive at most one fd
        # TODO: Unless messages with more delay when we received the keymap event fds?
        MAX_FD_COUNT = 1
        event_header_bytes, fds = self._recv_fds_exact(WAYLAND_MESSAGE_HEADER_SIZE_BYTES, MAX_FD_COUNT)
        self.fd_queue.extend(fds)
        object_id, length_and_opcode = struct.unpack("=II", event_header_bytes)
        length = length_and_opcode >> 16
        assert length % 4 == 0, "Length of message must be a multiple of 4."
        opcode = length_and_opcode & 0xFFFF
        event_data_bytes, fds = self._recv_fds_exact(length - WAYLAND_MESSAGE_HEADER_SIZE_BYTES, MAX_FD_COUNT)
        self.fd_queue.extend(fds)
        return object_id, length, opcode, event_data_bytes

    def send_message(self, object_id: int, opcode: int, data: bytes | bytearray):
        """Send a request to the Wayland server.

        Args:
            object_id: The ID of the object to send the request to.
            opcode: The opcode of the request.
            data: The data to send with the request.
        """
        length = WAYLAND_MESSAGE_HEADER_SIZE_BYTES + len(data)
        # Wayland messages are streams of 32-bit (4 byte) values
        assert length % 4 == 0, "Length of message must be a multiple of 4."
        # The length field is a 16-bit unsigned integer (the upper 16 bits of the 32-bit value)
        assert length < 2**16, "Length of message must be less than 2^16."
        length_and_opcode = (length << 16) | opcode
        message = struct.pack("=II", object_id, length_and_opcode)
        self._wayland_socket.sendall(message)
        self._wayland_socket.sendall(data)

    def shutdown(self):
        """Signal the Wayland connection to close and for the event loop to exit."""
        os.write(self._shutdown_pipe_write, b"\x00")

    def _recv_fds_exact(self, length: int, fd_count: int):
        """Receive exactly `length` bytes from the Wayland server and up to `fd_count` file descriptors.

        Returns:
            A tuple of (data bytes received, fds received)
        Raises:
            InterruptedError: if the connection is shut down using `WaylandConnection.shutdown()`.
        """
        fds = array.array("i")
        buffer = bytearray(length)
        view = memoryview(buffer)

        if length < 0:
            raise ValueError("Length must be non-negative.")
        if fd_count < 0:
            raise ValueError("FD count must be non-negative.")

        while length:
            for key, _ in self._selector.select():
                if key.fileobj == self._shutdown_pipe_read:
                    raise InterruptedError()
                # Based on Python3 socket.recvmsg docs (https://docs.python.org/3/library/socket.html#socket.socket.recvmsg)
                n, ancdata, flags, addr = self._wayland_socket.recvmsg_into([view], socket.CMSG_LEN(fd_count * fds.itemsize))
                for cmsg_level, cmsg_type, cmsg_data in ancdata:
                    if cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS:
                        # Append data, ignoring any truncated integers at the end.
                        fds.frombytes(cmsg_data[:len(cmsg_data) - (len(cmsg_data) % fds.itemsize)])
                # Advance write position in buffer
                view = view[n:]
                length -= n

        fds = list(fds)

        return buffer, fds


def wayland_keymap_event_loop(connection: WaylandConnection) -> tuple[int, int]:
    """Get the keymap from the Wayland server.
    See https://wayland.app/protocols/wayland for the opcodes and arguments
    
    Returns a tuple of (keymap_fd, keymap_size) as returned by the Wayland server.
    """
    # wl_display::get_registry
    # display id: DISPLAY_ID
    # opcode: 1
    # new id for registry: REGISTRY_ID
    connection.send_message(DISPLAY_ID, 1, struct.pack("=I", REGISTRY_ID))

    # wl_display::sync
    # display id: DISPLAY_ID
    # opcode: 0
    # new_id for callback: SYNC_ID
    connection.send_message(DISPLAY_ID, 0, struct.pack("=I", SYNC_ID))

    # Read all wl_display::get_registry events
    while True:
        object_id, length, opcode, event_data_bytes = connection.recv_message()
        if object_id == SYNC_ID:
            assert opcode == 0, f"Expected opcode 0 (wl_callback::done) for all events on wl_callback object (id {object_id})"
            break
        elif object_id == REGISTRY_ID and opcode == 0:
            # wl_registry::global
            name, interface_length = struct.unpack("=II", event_data_bytes[:8])
            # -1 to skip null terminator
            interface = event_data_bytes[8:8 + interface_length - 1].decode("utf-8")
            version_start_index = round_up_power_of_two(8 + interface_length, 4)
            version = struct.unpack("=I", event_data_bytes[version_start_index:version_start_index + 4])[0]
            print(f"Global: {name}, {interface}, {version}")

            if interface == "wl_seat":
                seat_name = event_data_bytes
                # Bind to seat using wl_registry::bind
                # opcode 0
                # the new_id arg follows custom serialization rules (interface name, version, id). See the representation of new_id in https://wayland.freedesktop.org/docs/html/ch04.html#sect-Protocol-Wire-Format
                # new id for seat: SEAT_ID
                data = seat_name + struct.pack("=I", SEAT_ID)
                connection.send_message(REGISTRY_ID, 0, data)
        else:
            print("Ignoring event for object", object_id, "opcode", opcode)

    # Read all wl_seat events
    has_keyboard = False
    while True:
        object_id, length, opcode, event_data_bytes = connection.recv_message()
        if object_id == SEAT_ID and opcode == 0:
            # wl_seat::capabilities
            assert opcode == 0
            assert length == WAYLAND_MESSAGE_HEADER_SIZE_BYTES + 4, f"Expected enum to be 4 bytes, got {length}"

            capabilities = struct.unpack("=I", event_data_bytes[:4])[0]
            print(f"Capabilities: {capabilities}")
            has_keyboard = capabilities & 2
            break
        elif object_id == DISPLAY_ID and opcode == 0:
            # wl_display::error
            raise RuntimeError(f"Wayland error: {repr(event_data_bytes)}")
        elif object_id == DISPLAY_ID and opcode == 1:
            # wl_display::delete_id
            assert length == WAYLAND_MESSAGE_HEADER_SIZE_BYTES + 4
            id_num = struct.unpack("=I", event_data_bytes[:4])[0]
            print(f"Deleted id: {id_num}")
        else:
            print("Ignoring event for object", object_id, "opcode", opcode)

    if not has_keyboard:
        raise ValueError("No keyboard")

    # Get wl_keyboard
    connection.send_message(SEAT_ID, 1, struct.pack("=I", KEYBOARD_ID))

    # Wait for and process wl_keyboard::keymap
    while True:
        object_id, length, opcode, event_data_bytes = connection.recv_message()
        if object_id == KEYBOARD_ID and opcode == 0:
            # wl_keyboard::keymap
            assert length == WAYLAND_MESSAGE_HEADER_SIZE_BYTES + 8

            keymap_format, keymap_size = struct.unpack("=II", event_data_bytes)
            print(f"Keymap format: {keymap_format}")
            if keymap_format != 1:
                raise RuntimeError(f"Unsupported keymap format: {keymap_format}")

            try:
                fd = connection.fd_queue.popleft()
            except IndexError:
                raise RuntimeError("No keymap fd received")

            print(f"Keymap size: {keymap_size}")
                
            return fd, keymap_size
        elif object_id == DISPLAY_ID and opcode == 0:
            # wl_display::error
            raise RuntimeError(f"Wayland error: {repr(event_data_bytes)}")
        else:
            print("Ignoring event for object", object_id, "opcode", opcode)

def compute_modifier_keycodes(keymap: xkb.Keymap) -> list[list[int]]:
    """
    Returns a list of xkbcommon keycodes for each non-latched or non-locked modifier in order of the modifier's index.
    If the modifier is latched or locked (e.g. NumLock), the keycode is None.
    `result[i]` is the keycode for the modifier with index `i`.

    If multiple keys produce the same modifier, an arbitrary one is chosen.
    """
    num_mods = keymap.num_mods()
    mod_index_to_mod_keycodes: list[list[int]] = [[] for _ in range(num_mods)]

    for keycode in keymap:
        # TODO: Why is this necessary?
        if xkb_keycode_to_ev_keycode(keycode) not in VALID_EV_KEYCODES:
            continue
        keyboard_state = xkb.KeyboardState(keymap)
        key_state = keyboard_state.update_key(keycode, xkb.KeyDirection.XKB_KEY_DOWN)

        is_key_mod = (key_state & xkb.StateComponent.XKB_STATE_MODS_DEPRESSED) and not ((key_state & xkb.StateComponent.XKB_STATE_MODS_LOCKED) or (key_state & xkb.StateComponent.XKB_STATE_MODS_LATCHED))
        if not is_key_mod:
            continue

        num_layouts = keymap.num_layouts_for_key(keycode)
        for layout in range(0, num_layouts):
            layout_is_active = keyboard_state.layout_index_is_active(layout, xkb.StateComponent.XKB_STATE_LAYOUT_EFFECTIVE)

            if not layout_is_active:
                continue

            for mod_index in range(num_mods):
                is_mod_active = keyboard_state.mod_index_is_active(mod_index, xkb.StateComponent.XKB_STATE_MODS_DEPRESSED)
                if not is_mod_active:
                    continue

                keysyms = keymap.key_get_syms_by_level(keycode, layout, 0)
                print("Modifier", keymap.mod_get_name(mod_index), "Keysyms:", keysyms, "Keycode:", keycode)
                if len(keysyms) != 1:
                    continue

                mod_index_to_mod_keycodes[mod_index].append(keycode)
            # break

    return mod_index_to_mod_keycodes

@contextlib.contextmanager
def fd_context(fd: int):
    try:
        yield fd
    finally:
        os.close(fd)

def get_wayland_keymap(timeout: float) -> xkb.Keymap:
    with WaylandConnection() as connection:
        done = False
        def timeout_thread_function():
            import time
            time.sleep(timeout)
            if not done:
                connection.shutdown()

        timeout_thread = threading.Thread(target=timeout_thread_function)
        timeout_thread.start()

        try:
            keymap_fd, keymap_size = wayland_keymap_event_loop(connection)
            done = True
        except InterruptedError:
            raise TimeoutError("Wayland get keymap timeout")
    with fd_context(keymap_fd) as keymap_fd:
        xkb_context = xkb.Context()
        with mmap.mmap(keymap_fd, keymap_size, flags=mmap.MAP_PRIVATE, prot=mmap.PROT_READ) as keymap_file:
            return xkb_context.keymap_new_from_file(keymap_file)

def generate_plover_keymap_from_xkb_keymap(keymap: xkb.Keymap, modifier_index_to_keycode: list[list[int]] | None = None) -> dict[str, KeyCodeInfo]:
    """
    Generate a mapping of Plover key names (key names used in dictionary entries) to `KeyCodeInfo` objects.
    `modifier_index_to_keycode` is optional and should be the result of `compute_modifier_keycodes`. If it is not provided, `compute_modifier_keycodes` will be called to compute it. It is a parameter to avoid recomputing the modifier keycodes if they are needed multiple times.
    """
    if modifier_index_to_keycode is None:
        modifier_index_to_keycode = compute_modifier_keycodes(keymap)
    # The following code in this function was based off of the now-removed `oslayer/linux/xkb_symbols.py` (https://github.com/openstenoproject/plover/blob/18aaf5174a0feaa5b4e3fea2fbce72bcc1d9f561/plover/oslayer/linux/xkb_symbols.py)
    plover_key_to_keycode: dict[str, KeyCodeInfo] = {}

    layout_index = 0
    for key in iter(keymap):
        if key - XKB_TO_EV_KEYCODE_OFFSET not in VALID_EV_KEYCODES:
            continue
        try:
            # Levels are different outputs from the same key with modifiers pressed
            level_count = keymap.num_levels_for_key(key, layout_index)

            for level in range(level_count):
                key_syms_for_level = keymap.key_get_syms_by_level(key, layout_index, level)
                for key_sym in key_syms_for_level:
                    key_name_for_level = xkb.keysym_get_name(key_sym)
                    key_for_level = xkb.keysym_to_string(key_sym)

                    modifier_masks_for_level = keymap.key_get_mods_for_level(key, layout_index, level)
                    key_modifiers: list[int] = []
                    # Identify sets of modifiers pressed to obtain this key and this level
                    # Each `mask` is a bitfield of modifiers pressed
                    for mask in modifier_masks_for_level:
                        modifier_index = 0
                        while mask > 0:
                            if mask & 1:
                                modifier_keycodes = modifier_index_to_keycode[modifier_index]
                                if not modifier_keycodes:
                                    break
                                # Arbitrarily use the first keycode for the modifier if the modifier has multiple keycodes
                                key_modifiers.append(modifier_keycodes[0] - XKB_TO_EV_KEYCODE_OFFSET)
                            mask >>= 1
                            modifier_index += 1
                        else:
                            break

                    if key_for_level is not None and key_for_level not in plover_key_to_keycode:
                        # Because we iterate levels in order, only the lowest level and thus simplest set of modifiers for each symbol is added.
                        # However, if multiple keys produce the same symbol, only the first key in iteration order is added. Same for level_key_name and aliases below
                        plover_key_to_keycode[key_for_level] = KeyCodeInfo(key - XKB_TO_EV_KEYCODE_OFFSET, key_modifiers)

                    for level_key_alias in XKB_KEY_NAME_TO_ALIASES.get(key_name_for_level, []):
                        if level_key_alias not in plover_key_to_keycode:
                            plover_key_to_keycode[level_key_alias] = KeyCodeInfo(key - XKB_TO_EV_KEYCODE_OFFSET, key_modifiers)

                    if key_name_for_level.startswith("XF86"):
                        plover_key_name = key_name_for_level[4:].lower()
                        # Add alias with "xf86" for XF86... keys to be consistent with X11 plover
                        if plover_key_name not in plover_key_to_keycode:
                            plover_key_to_keycode[plover_key_name] = KeyCodeInfo(key - XKB_TO_EV_KEYCODE_OFFSET, key_modifiers)

                    level_key_name_lower = key_name_for_level.lower()
                    if level_key_name_lower not in plover_key_to_keycode:
                        plover_key_to_keycode[level_key_name_lower] = KeyCodeInfo(key - XKB_TO_EV_KEYCODE_OFFSET, key_modifiers)

        except xkb.XKBInvalidKeycode:
            # Iter *should* return only valid, but still returns some invalid...
            pass

    # The "Linefeed" symbol (xkb symbol 0xff0a) has the key string "\n".
    # If Linefeed appears before the enter/return key when iterating over keys in the keymap (which is the case for qwerty), "\n" will be mapped to Linefeed rather than enter.
    # This ensures that "\n" is mapped to the enter/return key
    if "return" in plover_key_to_keycode:
        plover_key_to_keycode["\n"] = plover_key_to_keycode["return"]

    return plover_key_to_keycode


context = xkb.Context()

DEFAULT_LAYOUT = "qwerty"
LAYOUTS = {
    "qwerty": generate_plover_keymap_from_xkb_keymap(context.keymap_new_from_names(layout="us")),
    "qwertz": generate_plover_keymap_from_xkb_keymap(context.keymap_new_from_names(layout="de")),
    "dvorak": generate_plover_keymap_from_xkb_keymap(context.keymap_new_from_names(layout="us", variant="dvorak")),
    "colemak": generate_plover_keymap_from_xkb_keymap(context.keymap_new_from_names(layout="us", variant="colemak")),
    "colemak-dh": generate_plover_keymap_from_xkb_keymap(context.keymap_new_from_names(layout="us", variant="colemak_dh")),
}

# Linux EV keycode to Plover key name, used with suppressed keys
# Many key names are different from xkbcommon, so it's easier to define manually
HANDLED_KEYCODE_TO_KEY = {
    e.KEY_F1: "F1",
    e.KEY_F2: "F2",
    e.KEY_F3: "F3",
    e.KEY_F4: "F4",
    e.KEY_F5: "F5",
    e.KEY_F6: "F6",
    e.KEY_F7: "F7",
    e.KEY_F8: "F8",
    e.KEY_F9: "F9",
    e.KEY_F10: "F10",
    e.KEY_F11: "F11",
    e.KEY_F12: "F12",
    e.KEY_GRAVE: "`",
    e.KEY_0: "0",
    e.KEY_1: "1",
    e.KEY_2: "2",
    e.KEY_3: "3",
    e.KEY_4: "4",
    e.KEY_5: "5",
    e.KEY_6: "6",
    e.KEY_7: "7",
    e.KEY_8: "8",
    e.KEY_9: "9",
    e.KEY_MINUS: "-",
    e.KEY_EQUAL: "=",
    e.KEY_Q: "q",
    e.KEY_W: "w",
    e.KEY_E: "e",
    e.KEY_R: "r",
    e.KEY_T: "t",
    e.KEY_Y: "y",
    e.KEY_U: "u",
    e.KEY_I: "i",
    e.KEY_O: "o",
    e.KEY_P: "p",
    e.KEY_LEFTBRACE: "[",
    e.KEY_RIGHTBRACE: "]",
    e.KEY_BACKSLASH: "\\",
    e.KEY_A: "a",
    e.KEY_S: "s",
    e.KEY_D: "d",
    e.KEY_F: "f",
    e.KEY_G: "g",
    e.KEY_H: "h",
    e.KEY_J: "j",
    e.KEY_K: "k",
    e.KEY_L: "l",
    e.KEY_SEMICOLON: ";",
    e.KEY_APOSTROPHE: "'",
    e.KEY_Z: "z",
    e.KEY_X: "x",
    e.KEY_C: "c",
    e.KEY_V: "v",
    e.KEY_B: "b",
    e.KEY_N: "n",
    e.KEY_M: "m",
    e.KEY_COMMA: ",",
    e.KEY_DOT: ".",
    e.KEY_SLASH: "/",
    e.KEY_SPACE: "space",
    e.KEY_BACKSPACE: "BackSpace",
    e.KEY_DELETE: "Delete",
    e.KEY_DOWN: "Down",
    e.KEY_END: "End",
    e.KEY_ESC: "Escape",
    e.KEY_HOME: "Home",
    e.KEY_LEFT: "Left",
    e.KEY_PAGEDOWN: "Page_Down",
    e.KEY_PAGEUP: "Page_Up",
    e.KEY_ENTER: "Return",
    e.KEY_RIGHT: "Right",
    e.KEY_TAB: "Tab",
    e.KEY_UP: "Up",
}

print("Handled keys", HANDLED_KEYCODE_TO_KEY)
# Make sure no keys missing. Last 5 are "\t\n\r\x0b\x0c" which don't need to be handled
assert all(c in LAYOUTS[DEFAULT_LAYOUT].keys() for c in string.printable[:-5])

del context

if __name__ == "__main__":
    symbols = get_wayland_keymap(5)
    print(symbols)
