from evdev import InputDevice, list_devices, categorize

if __name__ == "__main__":
    devices = [InputDevice(path) for path in list_devices()]

    for device in devices:
        print(device)

    devices = InputDevice("/dev/input/event16")
    for event in devices.read_loop():
        print(categorize(event))
