from dataclasses import dataclass
from functools import partial
import mmap
import time

from pywayland.client.display import Display
from pywayland.protocol.wayland.wl_registry import WlRegistry
from pywayland.protocol.wayland.wl_seat import WlSeat
from pywayland.protocol.wayland.wl_keyboard import WlKeyboard

from xkbcommon import xkb

import evdev

@dataclass
class Info:
    
    roundtrip_needed: bool = False

def handle_registry_global(info: Info, registry: WlRegistry, id_num: int, interface: str, version: int) -> None:
    if interface == "wl_seat":
        seat = registry.bind(id_num, WlSeat, version)
        seat.dispatcher["name"] = lambda _, name: print(f"name: {name}")
        seat.dispatcher["capabilities"] = lambda _, capabilities: print(f"capabilities: {capabilities}")
        info.roundtrip_needed = True

        def handle_keymap(_, format: int, fd: int, size: int):
            print(f"format: {format}, fd: {fd}, size: {size}")
            if format != WlKeyboard.keymap_format.xkb_v1:
                print(f"Unsupported keymap format: {format}")
                return
            
            xkb_context = xkb.Context()
            
            with mmap.mmap(fd, size, flags=mmap.MAP_PRIVATE, prot=mmap.PROT_READ) as keymap_file:
                keymap = xkb_context.keymap_new_from_buffer(keymap_file, length=size)

            syms = keymap.key_get_syms_by_level(26, 1, 0)
            if syms:
                print("Keycode 26 symbols:", *(xkb.keysym_get_name(sym) for sym in syms), sep=" ")

            # time.sleep(2)
            # with evdev.UInput() as uinput:
            #     print("Sending")
            #     uinput.write(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_E, 1)
            #     uinput.write(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_E, 0)
            #     uinput.syn()
            
            # print(f"keymap: {keymap}")
            # print(f"keymap layout: {keymap.layout_get_name(0)}")
            # for code in keymap:
            #     print(f"code: {code}")
            #     try:
            #         print("code", code, "name", keymap.key_get_name(code))
            #         syms = keymap.key_get_syms_by_level(code, 1, 0)
            #         for sym in syms:
            #             if sym_name := xkb.keysym_get_name(sym):
            #                 print("sym", sym_name)
            #     except Exception as e:
            #         pass


        keyboard: WlKeyboard = seat.get_keyboard()
        keyboard.dispatcher["keymap"] = handle_keymap
    else:
        print("Unhandled interface", interface)
        

def main():
    info = Info()

    with Display() as display:
        registry = display.get_registry()
        registry.dispatcher["global"] = partial(handle_registry_global, info)
        display.dispatch()
        while True:
            # info.roundtrip_needed = False
            display.roundtrip()
            # if not info.roundtrip_needed:
            #     break
        print(info)


if __name__ == "__main__":
    main()