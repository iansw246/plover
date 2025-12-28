from xkbcommon import xkb

# mod_name = 'Shift' # or mod_name = 'Control'
mod_name = 'Control'

context = xkb.Context()
keymap = context.keymap_new_from_names(layout="us", options="caps:ctrl_modifier")
num_mods = keymap.num_mods()

for keycode in keymap:
    keyboard_state = xkb.KeyboardState(keymap)
    key_state = keyboard_state.update_key(keycode, xkb.KeyDirection.XKB_KEY_DOWN)

    num_layouts = keymap.num_layouts_for_key(keycode)
    for layout in range(0, num_layouts):

        layout_is_active = keyboard_state.layout_index_is_active(layout, xkb.StateComponent.XKB_STATE_LAYOUT_EFFECTIVE)

        if layout_is_active:
            for mod_index in range(0, num_mods):

                is_key_mod = key_state | xkb.StateComponent.XKB_STATE_MODS_DEPRESSED
                if is_key_mod:

                    is_mod_active = keyboard_state.mod_index_is_active(mod_index, xkb.StateComponent.XKB_STATE_MODS_DEPRESSED)
                    if is_mod_active:
                        if keymap.mod_get_name(mod_index) == mod_name:

                            keysyms = keymap.key_get_syms_by_level(keycode, layout, 0)

                            if len(keysyms) != 1:
                                continue

                            keysym_name = xkb.keysym_get_name(keysyms[0])
                            print(mod_name)
                            print(keycode)
                            print(keysym_name)

# context = xkb.Context()

# keymap = context.keymap_new_from_names(layout="gb")
# num_mods = keymap.num_mods()

# for keycode in keymap:
#     keyboard_state = xkb.KeyboardState(keymap)
#     key_state = keyboard_state.update_key(keycode, xkb.KeyDirection.XKB_KEY_DOWN)

#     is_key_mod = (key_state & xkb.StateComponent.XKB_STATE_MODS_DEPRESSED) and not ((key_state & xkb.StateComponent.XKB_STATE_MODS_LOCKED) or (key_state & xkb.StateComponent.XKB_STATE_MODS_LATCHED))
#     if not is_key_mod:
#         continue

#     num_layouts = keymap.num_layouts_for_key(keycode)
#     for layout in range(0, num_layouts):

#         layout_is_active = keyboard_state.layout_index_is_active(layout, xkb.StateComponent.XKB_STATE_LAYOUT_EFFECTIVE)

#         if not layout_is_active:
#             continue

#         for mod_index in range(0, num_mods):
#             is_mod_active = keyboard_state.mod_index_is_active(mod_index, xkb.StateComponent.XKB_STATE_MODS_DEPRESSED)
#             if not is_mod_active:
#                 continue

#             mod_name = keymap.mod_get_name(mod_index)

#             keysyms = keymap.key_get_syms_by_level(keycode, layout, 0)

#             if len(keysyms) != 1:
#                 continue

#             keysym_name = xkb.keysym_get_name(keysyms[0])
#             print("==Mod name==", mod_name)
#             print("Layout name", keymap.layout_get_name(layout))
#             print("Keycode", keycode)
#             print("Keysym name", keysym_name)
#             print("Key state", key_state)
