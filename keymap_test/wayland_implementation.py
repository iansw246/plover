import array
import collections
import mmap
import os
import socket
import struct
from xkbcommon import xkb

WAYLAND_MESSAGE_HEADER_SIZE_BYTES = 8

DISPLAY_ID = 1
REGISTRY_ID = 2
SYNC_ID = 3
SEAT_ID = 4
KEYBOARD_ID = 5

def recv_exact(socket: socket.socket, length: int):
    buffer = bytearray(length)
    view = memoryview(buffer)
    while length:
        n = socket.recv_into(view, length)
        if n == 0:
            raise EOFError
        view = view[n:]
        length -= n
    assert(length == 0)
    return buffer

def recv_fds_exact(s: socket.socket, length: int, fd_count: int):
    """Receive exactly `length` bytes from the given socket and `fd_count` file descriptors.
    
    Returns a tuple of (data_bytes, fds)
    """
    # Based on Python3 socket.recvmsg docs (https://docs.python.org/3/library/socket.html#socket.socket.recvmsg)
    fds = array.array("i")
    buffer = bytearray(length)
    view = memoryview(buffer)

    while length:
        n, ancdata, flags, addr = s.recvmsg_into([view], socket.CMSG_LEN(fd_count * fds.itemsize))
        for cmsg_level, cmsg_type, cmsg_data in ancdata:
            if cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS:
                fds.frombytes(cmsg_data[:len(cmsg_data) - (len(cmsg_data) % fds.itemsize)])
        view = view[n:]
        length -= n

    fds = list(fds)

    return buffer, fds

def round_up(value: int, multiple: int):
    """Round `value` up to the nearest multiple of `multiple`.
    `multiple` must be positive and a power of 2"""
    assert multiple & 1 == 0
    return (value + multiple - 1) & ~(multiple - 1)

class WaylandConnection:
    wayland_socket: socket.socket
    fd_queue: collections.deque[int]

    def __init__(self):
        self.fd_queue = collections.deque()

    def __enter__(self):
        wayland_display = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
        xdg_runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "")
        socket_path = os.path.join(xdg_runtime_dir, wayland_display)

        self.wayland_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.wayland_socket.connect(socket_path)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.wayland_socket.close()

    def recv_message(self):
        """Receive an event from the Wayland server.
        
        Returns a tuple of (object_id, length, opcode, event_data_bytes)
        """
        # The only event we care about is wl_keyboard::keymap which only has one fd
        MAX_FD_COUNT = 1
        event_header_bytes, fds = recv_fds_exact(self.wayland_socket, WAYLAND_MESSAGE_HEADER_SIZE_BYTES, MAX_FD_COUNT)
        self.fd_queue.extend(fds)
        object_id, length_and_opcode = struct.unpack("=II", event_header_bytes)
        length = length_and_opcode >> 16
        assert length % 4 == 0, "Length of message must be a multiple of 4."
        opcode = length_and_opcode & 0xFFFF
        event_data_bytes, fds = recv_fds_exact(self.wayland_socket, length - WAYLAND_MESSAGE_HEADER_SIZE_BYTES, MAX_FD_COUNT)
        self.fd_queue.extend(fds)
        return object_id, length, opcode, event_data_bytes

    def send_message(self, object_id: int, opcode: int, data: bytes | bytearray):
        """Send a request to the Wayland server.
        
        `object_id` is the ID of the object to send the request to.
        `opcode` is the opcode of the request.
        `data` is the data to send with the request.
        """
        length = WAYLAND_MESSAGE_HEADER_SIZE_BYTES + len(data)
        # Wayland messages are streams of 32-bit (4 byte) values
        assert length % 4 == 0, "Length of message must be a multiple of 4."
        # The length field is a 16-bit unsigned integer (the upper 16 bits of the 32-bit value)
        assert length < 2**16, "Length of message must be less than 2^16."
        length_and_opcode = (length << 16) | opcode
        message = struct.pack("=II", object_id, length_and_opcode)
        self.wayland_socket.sendall(message)
        self.wayland_socket.sendall(data)

with WaylandConnection() as connection:
    # wl_display::get_registry
    # display id: DISPLAY_ID
    # opcode: 1
    # new id for register: REGISTRY_ID
    connection.send_message(DISPLAY_ID, 1, struct.pack("=I", REGISTRY_ID))

    # wl_display::sync
    # display id: DISPLAY_ID
    # opcode: 0
    # new_id for callback: SYNC_ID
    connection.send_message(DISPLAY_ID, 0, struct.pack("=I", SYNC_ID))

    while True:
        object_id, length, opcode, event_data_bytes = connection.recv_message()
        if object_id == SYNC_ID:
            # wl_callback::done
            assert opcode == 0
            break
        elif object_id == REGISTRY_ID and opcode == 0:
            # wl_registry::global
            name, interface_length = struct.unpack("=II", event_data_bytes[:8])
            # -1 to skip null terminator
            interface = event_data_bytes[8:8 + interface_length - 1].decode("utf-8")
            version_start_index = round_up(8 + interface_length, 4)
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

    has_keyboard = False
    while True:
        object_id, length, opcode, event_data_bytes = connection.recv_message()
        if object_id == SYNC_ID:
            # wl_callback::done
            assert opcode == 0
            # Skip callback_data
            print("Done receiving seat events")
            break
        elif object_id == SEAT_ID and opcode == 0:
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

    fds: list[int] = []
    # Wait for wl_keyboard::keymap
    while True:
        object_id, length, opcode, event_data_bytes = connection.recv_message()
        if object_id == KEYBOARD_ID and opcode == 0:
            # wl_keyboard::keymap
            assert length == WAYLAND_MESSAGE_HEADER_SIZE_BYTES + 8

            keymap_format, keymap_size = struct.unpack("=II", event_data_bytes)
            print(f"Keymap format: {keymap_format}")
            if keymap_format != 1:
                raise ValueError(f"Unsupported keymap format: {keymap_format}")

            fd = connection.fd_queue.popleft()

            if not fd:
                raise ValueError("No keymap fd received")

            print(f"Keymap size: {keymap_size}")
                
            xkb_context = xkb.Context()
            with mmap.mmap(fd, keymap_size, flags=mmap.MAP_PRIVATE, prot=mmap.PROT_READ) as keymap_file:
                keymap = xkb_context.keymap_new_from_file(keymap_file)
                
            syms = keymap.key_get_syms_by_level(26, 1, 0)
            if syms:
                print("Keycode 26 symbols:", *(xkb.keysym_get_name(sym) for sym in syms), sep=" ")
            break
        else:
            print("Ignoring event for object", object_id, "opcode", opcode)
