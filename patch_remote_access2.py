import re

with open('linux_rdaccess_core/connection/remote_access.py', 'r') as f:
    code = f.read()

# Replace the whole block of if/elif for browse_action
block_to_replace = '''            if vk_code == 0x46 and ctrl and not shifts and not alt_win:   # NVDA+Ctrl+F
                browse_action = "find"
            elif vk_code == 0x56 and not shifts and not ctrl and not alt_win:  # NVDA+V
                browse_action = "layout"
            elif vk_code == 0x72 and not ctrl and not alt_win:            # NVDA+F3/Shift+F3
                browse_action = "findPrevious" if shifts else "findNext"
            elif vk_code == 0x79 and shifts and not ctrl and not alt_win: # NVDA+Shift+F10'''

new_block = '''            if vk_code == 0x56 and not shifts and not ctrl and not alt_win:  # NVDA+V
                browse_action = "layout"
            elif vk_code == 0x79 and shifts and not ctrl and not alt_win: # NVDA+Shift+F10'''

code = code.replace(block_to_replace, new_block)

with open('linux_rdaccess_core/connection/remote_access.py', 'w') as f:
    f.write(code)

print("Patched.")
