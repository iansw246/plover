def wayland_test():
    import wayland
    import time

    def on_keymap(format: wayland.wl_keyboard.keymap_format, fd: int, size: int) -> None:
        print(format, fd, size)
    
    def on_global(name: int, interface: str, version: int) -> None:
        print("On global", name, interface, version)
        if interface == "wl_seat":
            wayland.wl_seat = wayland.wl_registry.bind(name, interface, 0, 0)
        # elif interface == "wl_keyboard":
        #     wayland.wl_keyboard = wayland.wl_registry.bind(name, interface, 0, 1)


    wayland.wl_registry.events.global_+= on_global
    registry = wayland.wl_display.get_registry()
    for i in range(500):
        wayland.process_messages()
        time.sleep(0.01)
    print("registry", registry)
    wayland.wl_keyboard.events.keymap += on_keymap

    wayland.process_messages()


    keyboard = wayland.wl_seat.get_keyboard()
    

wayland_test()