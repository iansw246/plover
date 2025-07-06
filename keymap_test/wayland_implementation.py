import array
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
    assert multiple & 1 == 0
    return (value + multiple - 1) & ~(multiple - 1)

wayland_display = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
xdg_runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "")
socket_path = os.path.join(xdg_runtime_dir, wayland_display)

with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
    s.connect(socket_path)

    # wl_display::get_registry
    # display id: 1
    # length: 12 bytes
    # opcode: 1
    # new id for register: 2
    length_and_opcode = (12 << 16) | 1
    message = struct.pack("=III", DISPLAY_ID, length_and_opcode, REGISTRY_ID)
    s.sendall(message)

    # wl_display::sync
    # display id: 1
    # length: 12 bytes
    # opcode: 0
    # new_id for callback: 3
    length_and_opcode = (12 << 16) | 0
    message = struct.pack("=III", DISPLAY_ID, length_and_opcode, SYNC_ID)
    s.sendall(message)

    done = False
    while not done:
        event_header_bytes = recv_exact(s, WAYLAND_MESSAGE_HEADER_SIZE_BYTES)
        object_id, length_and_opcode = struct.unpack("=II", event_header_bytes)
        length = length_and_opcode >> 16
        opcode = length_and_opcode & 0xFFFF
        if object_id == SYNC_ID:
            # wl_callback::done
            assert opcode == 0
            # Skip callback_data
            recv_exact(s, 4)
            done = True
            print("Done receiving global objects")
            continue
        elif object_id == REGISTRY_ID:
            # wl_registry::global
            assert opcode == 0
            event_data_bytes = recv_exact(s, length - WAYLAND_MESSAGE_HEADER_SIZE_BYTES)
            name, interface_length = struct.unpack("=II", event_data_bytes[:8])
            # -1 to skip null terminator
            interface = event_data_bytes[8:8 + interface_length - 1].decode("utf-8")
            version_start_index = round_up(8 + interface_length, 4)
            version = struct.unpack("=I", event_data_bytes[version_start_index:version_start_index + 4])[0]
            print(f"Global: {name}, {interface}, {version}")

            if interface == "wl_seat":
                seat_name = event_data_bytes
                # # Bind to seat
                length = (WAYLAND_MESSAGE_HEADER_SIZE_BYTES + len(seat_name) + 4)
                length_and_opcode = (length << 16) | 0
                message = struct.pack("=II", REGISTRY_ID, length_and_opcode) + seat_name + struct.pack("=I", SEAT_ID)
                assert len(message) == length
                print("Binding seat", message)
                s.sendall(message)

                # Bind to seat
                # length = WAYLAND_MESSAGE_HEADER_SIZE_BYTES + 8
                # length_and_opcode = (length << 16) | 0
                # message = struct.pack("=IIII", REGISTRY_ID, length_and_opcode, name, SEAT_ID)
                # assert len(message) == length
                # print("Sending bind request", message)
                # s.sendall(message)

                # wl_display::sync
                # display id: 1
                # length: 12 bytes
                # opcode: 0
                # new_id for callback: 3
                # length_and_opcode = (12 << 16) | 0
                # message = struct.pack("=III", DISPLAY_ID, length_and_opcode, SYNC_ID)
                # s.sendall(message)

        else:
            raise ValueError(f"Unknown object id: {object_id}")

    done = False
    has_keyboard = False
    while not done:
        event_header_bytes = recv_exact(s, WAYLAND_MESSAGE_HEADER_SIZE_BYTES)
        object_id, length_and_opcode = struct.unpack("=II", event_header_bytes)
        length = length_and_opcode >> 16
        opcode = length_and_opcode & 0xFFFF
        if object_id == SYNC_ID:
            # wl_callback::done
            assert opcode == 0
            # Skip callback_data
            recv_exact(s, 4)
            done = True
            print("Done receiving seat events")
            continue
        elif object_id == SEAT_ID:
            # wl_seat::capabilities
            if opcode != 0:
                print("Ignoring seat event", opcode)
                recv_exact(s, length - WAYLAND_MESSAGE_HEADER_SIZE_BYTES)
                continue

            assert length == WAYLAND_MESSAGE_HEADER_SIZE_BYTES + 4, f"Expected enum to be 4 bytes, got {length}"
            event_data_bytes = recv_exact(s, length - WAYLAND_MESSAGE_HEADER_SIZE_BYTES)
            capabilities = struct.unpack("=I", event_data_bytes[:4])[0]
            print(f"Capabilities: {capabilities}")
            if capabilities & 2:
                # wl_seat::get_keyboard
                has_keyboard = True
            break
        elif object_id == DISPLAY_ID:
            if opcode == 0:
                # wy_display::error
                raise RuntimeError(f"Wayland error: {repr(recv_exact(s, length - WAYLAND_MESSAGE_HEADER_SIZE_BYTES).decode('utf-8'))}")
            if opcode == 1:
                # wl_display::delete_id
                assert length == WAYLAND_MESSAGE_HEADER_SIZE_BYTES + 4
                event_data_bytes = recv_exact(s, length - WAYLAND_MESSAGE_HEADER_SIZE_BYTES)
                id_num = struct.unpack("=I", event_data_bytes[:4])[0]
                print(f"Deleted id: {id_num}")
            else:
                raise ValueError(f"Unknown opcode: {opcode}")
        else:
            raise ValueError(f"Unknown object id: {object_id}. Length: {length}, opcode: {opcode}")

    if not has_keyboard:
        raise ValueError("No keyboard")

    # Get wl_keyboard
    length_and_opcode = (12 << 16) | 1
    message = struct.pack("=III", SEAT_ID, length_and_opcode, KEYBOARD_ID)
    s.sendall(message)

    # Wait for wl_keyboard::keymap
    while True:

        event_header_bytes, fds = recv_fds_exact(s, WAYLAND_MESSAGE_HEADER_SIZE_BYTES, 1)
        object_id, length_and_opcode = struct.unpack("=II", event_header_bytes)
        length = length_and_opcode >> 16
        opcode = length_and_opcode & 0xFFFF
        if object_id == KEYBOARD_ID:
            if opcode == 0:
                # wl_keyboard::keymap
                assert length == WAYLAND_MESSAGE_HEADER_SIZE_BYTES + 8

                event_data_bytes, new_fds = recv_fds_exact(s, 8, 1)
                fds += new_fds
                keymap_format, keymap_size = struct.unpack("=II", event_data_bytes)
                print(f"Keymap format: {keymap_format}")
                if keymap_format != 1:
                    raise ValueError(f"Unsupported keymap format: {keymap_format}")

                if not fds:
                    raise ValueError("No keymap fd received")

                print(f"Keymap size: {keymap_size}")
                
                xkb_context = xkb.Context()
                with open(fds[0], "rb") as keymap_file:
                    keymap = xkb_context.keymap_new_from_file(keymap_file)

            else:
                print("Ignoring keyboard event", opcode)
                recv_exact(s, length - WAYLAND_MESSAGE_HEADER_SIZE_BYTES)
        else:
            raise ValueError(f"Unknown object id: {object_id}")

